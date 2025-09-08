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
from rply import LexerGenerator, Token, LexingError
from g1asm.data import parse_data
from g1asm.binary_format import G1BinaryFormat, format_json
from g1asm.instructions import INSTRUCTIONS, ARGUMENT_COUNT_LOOKUP, ASSIGNMENT_INSTRUCTIONS


class AssemblerState(Enum):
    META = 1
    PROCEDURES = 2


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


def get_until_newline(tokens: list[Token]) -> list[Token]:
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


def assemble_tokens(tokens: list[Token], source_lines: list[str], compiler_state: AssemblerState, include_source: bool=False) -> dict:
    output_json = {'meta': META_VARIABLES.copy()}
    
    labels = {}
    raw_instructions = []
    instruction_index = 0

    for token in tokens:
        if token.name == 'META_VARIABLE':
            if compiler_state != AssemblerState.META:
                error(token, source_lines, f'Found meta variable outside file header.')
            meta_variable_name = token.value[1:]
            if meta_variable_name not in META_VARIABLES:
                error(token, source_lines, f'Unrecognized meta variable "{meta_variable_name}".')
            output_json['meta'][meta_variable_name] = int(tokens.next().value)
        
        elif token.name == 'LABEL_NAME':
            if compiler_state != AssemblerState.PROCEDURES:
                compiler_state = AssemblerState.PROCEDURES
            label_name = token.value[:-1]
            if label_name in labels:
                warn(token, source_lines, f'Label "{label_name}" declared more than once.')
            else:
                labels[label_name] = instruction_index
        
        elif token.name == 'NAME':
            if token.value not in INSTRUCTIONS:
                error(token, source_lines, f'Unrecognized instruction "{token.value}".')

            instruction_name_token = token.value
            instruction_arg_amount = ARGUMENT_COUNT_LOOKUP[token.value]
            instruction_args = get_until_newline(tokens)
            if len(instruction_args) != instruction_arg_amount:
                error(token, source_lines, f'Expected {instruction_arg_amount} argument(s) for instruction "{instruction_name_token}" but got {len(instruction_args)}.')
            raw_instructions.append([token, instruction_args])
            instruction_index += 1
        
        elif token.name in {'NUMBER', 'ADDRESS'}:
            error(token, source_lines, 'Value outside of instruction.')
        
        elif token.name in {'COMMENT', 'NEWLINE'}:
            continue
    
    # Parse instruction args
    instructions = []
    for instruction_name_token, instruction_args_tokens in raw_instructions:
        instruction_name = instruction_name_token.value 
        instruction_args = [parse_argument_token(t, labels, source_lines) for t in instruction_args_tokens]
        instruction_data = [instruction_name, instruction_args]
        first_argument = instruction_args[0]
        if instruction_name in ASSIGNMENT_INSTRUCTIONS and isinstance(first_argument, int) and first_argument <= 11:
            warn(instruction_args_tokens[0], source_lines, 'Assignment to a reserved memory location.')
        if include_source:
            instruction_data.append(instruction_name_token.source_pos.lineno-1)
        instructions.append(instruction_data)
    
    output_json['instructions'] = instructions
    if 'tick' in labels:
        output_json['tick'] = labels['tick']
    else:
        print('WARNING: "tick" label not found in program.')
    if 'start' in labels:
        output_json['start'] = labels['start']
    
    if include_source:
        output_json['source'] = source_lines
    return output_json


def assemble(input_path: str, output_path: str, data_file_path: str|None, include_source: bool, output_format: OUTPUT_FORMATS):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'File "{input_path}" does not exist.')
    with open(input_path, 'r') as f:
        source_code = f.read()
    
    source_lines = source_code.split('\n')
    tokens = lexer.lex(source_code + '\n')
    try:
        output_json = assemble_tokens(tokens, source_lines, AssemblerState.META, include_source)
    except LexingError as e:
        error(e, source_lines, 'Unrecognized token.')
    
    # Add data entries
    if data_file_path is not None:
        if os.path.isfile(data_file_path):
            with open(data_file_path, 'r') as f:
                data = parse_data(f.read(), output_json['meta']['memory'])
                if data is not None:
                    output_json['data'] = data
        else:
            print('Could not find data file at "{data_file_path}".')

    # Set file content based on the output format
    if output_format == 'json':
        file_content = json.dumps(output_json, separators=(',', ':')).encode('utf-8')
    else:
        formatted_json = format_json(output_json)
        file_content = G1BinaryFormat.build(formatted_json)
    
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
