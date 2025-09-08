"""
Assembler implementation for the g1 ISA.

By Miles Burkart
https://github.com/7Limes
"""


import sys
import os
import json
from enum import Enum
from typing import Literal
import argparse
from dataclasses import dataclass, field
from rply import LexerGenerator, Token, LexingError
from rply.lexer import LexerStream
from g1asm.data import parse_data
from g1asm.binary_format import G1BinaryFormat, ARG_TYPE_LITERAL, ARG_TYPE_ADDRESS, OPCODE_LOOKUP
from g1asm.instructions import INSTRUCTIONS, ARGUMENT_COUNT_LOOKUP, ASSIGNMENT_INSTRUCTIONS


lg = LexerGenerator()
lg.add('META_VARIABLE', r'#[A-z]+')
lg.add('NUMBER', r'-?\d+')
lg.add('ADDRESS', r'\$\d+')
lg.add('LABEL_NAME', r'[A-z0-9_]+:')
lg.add('NAME', r'[A-z_][A-z0-9_]*')
lg.add('COMMENT', r';.*')
lg.add('NEWLINE', r'\n')
lg.ignore(r' ')
lexer = lg.build()


META_VARIABLES = {
    'memory': 128,
    'width': 100,
    'height': 100,
    'tickrate': 60
}

OUTPUT_FORMATS = Literal['json', 'g1b']
DEFAULT_OUTPUT_FORMAT = 'json'

INT_RANGE_LOWER = -2**31
INT_RANGE_UPPER = 2**31-1

COLOR_ERROR = '\x1b[31m'
COLOR_WARN = '\x1b[33m'
COLOR_RESET = '\x1b[0m'


class AssemblerState(Enum):
    META = 1
    PROCEDURES = 2


@dataclass
class AssemblerData:
    meta: dict[str, int] = field(default_factory=lambda: META_VARIABLES.copy())
    labels: dict[str, int] = field(default_factory=dict)
    instruction_tokens: list[tuple[Token, list[Token]]] = field(default_factory=list)
    instruction_index: int = 0
    state: AssemblerState = AssemblerState.META

    instructions: list[tuple[str, list[str | int], int]] = field(default_factory=list)
    start_label: int = -1
    tick_label: int = -1
    data_entries: list[tuple[int, list[int]]] | None = None

    source_lines: list[str] | None = None


    def add_data_entries(self, data_file_path: str):
        if os.path.isfile(data_file_path):
            with open(data_file_path, 'r') as f:
                data = parse_data(f.read(), self.meta['memory'])
                if data is not None:
                    self.data_entries = data
        else:
            print('Could not find data file at "{data_file_path}".')


    def assemble_json(self) -> bytes:
        output_json = {
            'meta': self.meta,
            'instructions': self.instructions
        }

        if self.start_label != -1:
            output_json['start'] = self.start_label
        if self.tick_label != -1:
            output_json['tick'] = self.tick_label
        
        if self.data_entries is not None:
            output_json['data'] = self.data_entries
        
        if self.source_lines is not None:
            output_json['source'] = self.source_lines
        
        return json.dumps(output_json, separators=(',', ':')).encode('utf-8')

    
    def assemble_binary(self) -> bytes:
        file_dict = {
            'meta': self.meta,
            'instruction_count': len(self.instructions),
            'start': self.start_label,
            'tick': self.tick_label
        }

        formatted_instructions = []
        for instruction_data in self.instructions:
            instruction_name, arguments = instruction_data[:2]  # only grab the first 2 in case of debug mode
            formatted_arguments = []
            for argument in arguments:
                if isinstance(argument, int):
                    formatted_arguments.append({'type': ARG_TYPE_LITERAL, 'value': argument})
                else:
                    formatted_arguments.append({'type': ARG_TYPE_ADDRESS, 'value': int(argument[1:])})
            instruction_opcode = OPCODE_LOOKUP[instruction_name]
            verbose_instruction = {
                'opcode': instruction_opcode,
                'arguments': formatted_arguments
            }
            formatted_instructions.append(verbose_instruction)
        file_dict['instructions'] = formatted_instructions

        if self.data_entries is not None:
            formatted_data_entries = []
            for address, data_values in self.data_entries:
                formatted_data_entries.append({'address': address, 'size': len(data_values), 'values': data_values})
            file_dict['data_entry_count'] = len(formatted_data_entries)
            file_dict['data'] = formatted_data_entries
        else:
            file_dict['data_entry_count'] = 0
            file_dict['data'] = {}
        
        return G1BinaryFormat.build(file_dict)


def error(token: Token, source_lines: list[str], message: str):
    line_number = token.source_pos.lineno-1
    column_number = token.source_pos.colno-1
    print(f'{COLOR_ERROR}ASSEMBLER ERROR: {message}')
    print(f'{line_number+1} | {source_lines[line_number]}')
    print(f'{" " * (len(str(line_number))+3+column_number)}^')
    print(COLOR_RESET, end='')
    sys.exit()


def warn(token: Token, source_lines: list[str], message: str):
    line_number = token.source_pos.lineno-1
    column_number = token.source_pos.colno-1
    print(f'{COLOR_WARN}ASSEMBLER WARNING: {message}')
    print(f'{line_number+1} | {source_lines[line_number]}')
    print(f'{" " * (len(str(line_number))+3+column_number)}^')
    print(COLOR_RESET, end='')


def get_until_newline(tokens: LexerStream) -> list[Token]:
    returned_tokens = []
    while True:
        token = tokens.next()
        if token.name == 'COMMENT':
            continue
        if token.name == 'NEWLINE':
            break
        returned_tokens.append(token)
    return returned_tokens


def parse_argument_token(token: Token, labels: dict[str, int], source_lines: list[str]) -> str | int:
    if token.name == 'NUMBER':
        parsed = int(token.value)
        if parsed < INT_RANGE_LOWER or parsed > INT_RANGE_UPPER:
            error(token, source_lines, f'Integer value {token.value} is outside the 32 bit signed integer range.')
        return parsed
    if token.name == 'NAME':
        if token.value not in labels:
            error(token, source_lines, f'Undefined label "{token.value}".')
        return labels[token.value]
    if token.name == 'ADDRESS':
        parsed_address = int(token.value[1:])
        if parsed_address < INT_RANGE_LOWER or parsed_address > INT_RANGE_UPPER:
            error(token, source_lines, f'Address value {token.value} is outside the 32 bit signed integer range.')
        return token.value
    return token.value


def assemble_tokens(tokens: LexerStream, source_lines: list[str], include_source: bool=False):
    assembler_data = AssemblerData()

    for token in tokens:
        if token.name == 'META_VARIABLE':
            if assembler_data.state != AssemblerState.META:
                error(token, source_lines, f'Found meta variable outside file header.')
            meta_variable_name = token.value[1:]
            if meta_variable_name not in META_VARIABLES:
                error(token, source_lines, f'Unrecognized meta variable "{meta_variable_name}".')
            assembler_data.meta[meta_variable_name] = int(tokens.next().value)
        
        elif token.name == 'LABEL_NAME':
            if assembler_data.state != AssemblerState.PROCEDURES:
                assembler_data.state = AssemblerState.PROCEDURES
            label_name = token.value[:-1]
            if label_name in assembler_data.labels:
                warn(token, source_lines, f'Label "{label_name}" declared more than once.')
            else:
                assembler_data.labels[label_name] = assembler_data.instruction_index
        
        elif token.name == 'NAME':
            if token.value not in INSTRUCTIONS:
                error(token, source_lines, f'Unrecognized instruction "{token.value}".')

            instruction_name_token = token.value
            instruction_arg_amount = ARGUMENT_COUNT_LOOKUP[token.value]
            instruction_args = get_until_newline(tokens)
            if len(instruction_args) != instruction_arg_amount:
                error(token, source_lines, f'Expected {instruction_arg_amount} argument(s) for instruction "{instruction_name_token}" but got {len(instruction_args)}.')
            assembler_data.instruction_tokens.append((token, instruction_args))
            assembler_data.instruction_index += 1
        
        elif token.name in {'NUMBER', 'ADDRESS'}:
            error(token, source_lines, 'Value outside of instruction.')
        
        elif token.name in {'COMMENT', 'NEWLINE'}:
            continue
    
    # Parse instruction args
    for instruction_name_token, instruction_args_tokens in assembler_data.instruction_tokens:
        instruction_name: str = instruction_name_token.value 
        instruction_args = [parse_argument_token(t, assembler_data.labels, source_lines) for t in instruction_args_tokens]
        first_argument = instruction_args[0]
        if instruction_name in ASSIGNMENT_INSTRUCTIONS and isinstance(first_argument, int) and first_argument <= 11:
            warn(instruction_args_tokens[0], source_lines, 'Assignment to a reserved memory location.')
        if include_source:
            instruction_data = (instruction_name, instruction_args, instruction_name_token.source_pos.lineno-1)
        else:
            instruction_data = (instruction_name, instruction_args)
        assembler_data.instructions.append(instruction_data)
    
    # Check for start and tick labels
    if 'tick' in assembler_data.labels:
        assembler_data.tick_label = assembler_data.labels['tick']
    else:
        print('WARNING: "tick" label not found in program.')
    if 'start' in assembler_data.labels:
        assembler_data.start_label = assembler_data.labels['start']
    
    # Add source lines if necessary
    if include_source:
        assembler_data.source_lines = source_lines
    
    return assembler_data


def assemble(input_path: str, output_path: str, data_file_path: str|None, include_source: bool, output_format: OUTPUT_FORMATS):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'File "{input_path}" does not exist.')
    with open(input_path, 'r') as f:
        source_code = f.read()
    
    source_lines = source_code.split('\n')
    tokens = lexer.lex(source_code + '\n')
    try:
        assembler_data = assemble_tokens(tokens, source_lines, include_source)
    except LexingError as e:
        error(e, source_lines, 'Unrecognized token.')
    
    # Add data entries
    if data_file_path is not None:
        assembler_data.add_data_entries(data_file_path)

    # Set file content based on the output format
    if output_format == 'json':
        file_content = assembler_data.assemble_json()
    else:
        file_content = assembler_data.assemble_binary()
    
    # Write the output file
    with open(output_path, 'wb') as f:
        f.write(file_content)


def main():
    try:
        parser = argparse.ArgumentParser(description='Assemble a g1 program')
        parser.add_argument('input_path', help='The path to the input g1 assembly program')
        parser.add_argument('output_path', help='The path to the assembled g1 program')
        parser.add_argument('--data_path', '-d', type=str, default=None, help='The path to a data file (.g1d) for the program')
        parser.add_argument('--include_source', '-src', action='store_true', help='Include the source lines in the assembled program. Only works if the output format is .json')
        parser.add_argument('--output_format', '-o', default=None, choices=['g1b', 'json'], help='The output format for the assembled program')
        args = parser.parse_args()
    except Exception as e:
        print(e)
        return 1

    if not os.path.isfile(args.input_path):
        print(f'Could not find file "{args[1]}"')
        return 2
    
    output_format = args.output_format
    if output_format is None:
        # Get format from output file extension
        implied_format = os.path.splitext(args.output_path)[1].replace('.', '')
        if implied_format in OUTPUT_FORMATS.__args__:
            output_format = implied_format
        else:
            output_format = DEFAULT_OUTPUT_FORMAT
    
    assemble(args.input_path, args.output_path, args.data_path, args.include_source, output_format)
    return 0


if __name__ == '__main__':
    sys.exit(main())
