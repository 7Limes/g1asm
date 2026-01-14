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
from dataclasses import dataclass
import re
from rply import LexerGenerator, Token, LexingError
from rply.lexer import LexerStream
from g1asm.data import parse_entry, G1ADataException
from g1asm.binary_format import G1BinaryFormat, ARG_TYPE_LITERAL, ARG_TYPE_ADDRESS, OPCODE_LOOKUP
from g1asm.instructions import INSTRUCTIONS, ARGUMENT_COUNT_LOOKUP, ASSIGNMENT_INSTRUCTIONS


DEFAULT_META_VARS = {
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

DATA_ENTRY_REGEX = r'@(\d+)\s+(file|bytes|string)\s+(raw|pack|img)\s+([\'\"\`])(.*)\4'


def build_lexer():
    lg = LexerGenerator()
    lg.add('META_VARIABLE', r'#[A-z]+')

    lg.add('NUMBER', r'-?\d+')
    lg.add('ADDRESS', r'\$\d+')
    lg.add('LABEL_NAME', r'[A-z0-9_]+:')
    lg.add('NAME', r'[A-z_][A-z0-9_]*')

    lg.add('DATA_ENTRY', DATA_ENTRY_REGEX)

    lg.add('COMMENT', r';.*')
    lg.add('NEWLINE', r'\n')
    lg.ignore(r' ')
    
    return lg.build()


class AssemblerState(Enum):
    META_VARS = 1
    DATA = 2
    SUBROUTINES = 3


@dataclass
class Instruction:
    name: str
    arguments: list[Token]
    line_number: int


@dataclass
class ParsedInstruction:
    name: str
    arguments: list[int | str]
    line_number: int

    def to_json(self, include_source: bool):
        if include_source:
            return (self.name, self.arguments, self.line_number)
        return (self.name, self.arguments)


@dataclass
class DataEntry:
    address: int
    data: list[int]

    def to_json(self):
        return (self.address, self.data)


class Assembler:
    def __init__(self, tokens: LexerStream, source_lines: list[str]):
        self.tokens = tokens
        self.source_lines = source_lines

        self.state = AssemblerState.META_VARS
        self.current_token = None

        self.meta_vars = DEFAULT_META_VARS.copy()
        self.labels: dict[str, int] = {}
        self.instruction_index: int = 0
        self.instructions: list[Instruction] = []

        self.parsed_instructions: list[ParsedInstruction] = []
        self.start_label: int = -1
        self.tick_label: int = -1
        self.data_entries: list[DataEntry] = []


    def error(self, message: str, token: Token | None=None):
        if token is None:
            token = self.current_token
        
        line_number = token.source_pos.lineno-1
        column_number = token.source_pos.colno-1
        print(f'{COLOR_ERROR}ASSEMBLER ERROR: {message}')
        print(f'{line_number+1} | {self.source_lines[line_number]}')
        print(f'{" " * (len(str(line_number))+3+column_number)}^')
        print(COLOR_RESET, end='')

        sys.exit()
    

    def warning(self, message: str, token: Token | None=None):
        if token is None:
            token = self.current_token
        
        line_number = token.source_pos.lineno-1
        column_number = token.source_pos.colno-1
        print(f'{COLOR_WARN}ASSEMBLER WARNING: {message}')
        print(f'{line_number+1} | {self.source_lines[line_number]}')
        print(f'{" " * (len(str(line_number))+3+column_number)}^')
        print(COLOR_RESET, end='')
    

    def next_token(self, token_name: str):
        try:
            next_tok = self.tokens.next()
        except StopIteration:
            self.error(f'Reached end of token stream while trying to get token "{token_name}"')
        
        if next_tok.name != token_name:
            self.error(next_tok, f'Expected "{token_name}" token but got "{next_tok.name}"')
        
        return next_tok

    def get_until_newline(self) -> list[Token]:
        returned_tokens = []
        while True:
            token = self.tokens.next()
            if token.name == 'COMMENT':
                continue
            if token.name == 'NEWLINE':
                break
            returned_tokens.append(token)
        return returned_tokens

    def parse_argument_token(self, token: Token) -> str | int:
        if token.name == 'NUMBER':
            parsed = int(token.value)
            if parsed < INT_RANGE_LOWER or parsed > INT_RANGE_UPPER:
                self.error(f'Integer value {token.value} is outside the 32 bit signed integer range.', token)
            return parsed
        
        elif token.name == 'NAME':
            if token.value not in self.labels:
                self.error(f'Undefined label "{token.value}".', token)
            return self.labels[token.value]

        elif token.name == 'ADDRESS':
            parsed_address = int(token.value[1:])
            if parsed_address < INT_RANGE_LOWER or parsed_address > INT_RANGE_UPPER:
                self.error(f'Address value {token.value} is outside the 32 bit signed integer range.', token)
            return token.value

        return token.value


    def check_misplaced_meta_var(self):
        if self.current_token.name == 'META_VARIABLE':
            self.error(f'Got a misplaced meta variable.')
    
    def check_misplaced_data_entry(self):
        if self.current_token.name == 'DATA_ENTRY':
            self.error(f'Got a misplaced data entry.')
    

    def check_data_entry_spans(self):
        spans = [[e.address, e.address+len(e.data)-1] for e in self.data_entries]
        spans.sort(key=lambda x: x[0])

        for i in range(len(spans)-1):
            for j in range(i+1, len(spans)):
                if spans[i][1] >= spans[j][0]:
                    self.warning(f'Data overlap found between {spans[i]} and {spans[j]}.')
    

    def parse_instruction_args(self):
        for instruction in self.instructions:
            parsed_args = [self.parse_argument_token(t) for t in instruction.arguments]
            first_argument = parsed_args[0]
            if instruction.name in ASSIGNMENT_INSTRUCTIONS and isinstance(first_argument, int) and first_argument <= 11:
                self.warning('Assignment to a reserved memory location.', parsed_args[0])

            self.parsed_instructions.append(
                ParsedInstruction(
                    instruction.name, parsed_args, instruction.line_number
                )
            )


    def assemble_meta_vars(self):
        if self.current_token.name == 'META_VARIABLE':
            meta_variable_name = self.current_token.value[1:]
            if meta_variable_name not in DEFAULT_META_VARS:
                self.error(f'Unrecognized meta variable "{meta_variable_name}".')
            
            value_token = self.next_token('NUMBER')
            self.meta_vars[meta_variable_name] = int(value_token.value)
        
        elif self.current_token.name == 'DATA_ENTRY':
            self.state = AssemblerState.DATA

        elif self.current_token.name == 'LABEL_NAME':
            self.state = AssemblerState.SUBROUTINES
        
        else:
            self.error(f'Expected meta variable definition but got "{self.current_token.name}".')


    def assemble_data_entries(self):
        self.check_misplaced_meta_var()

        if self.current_token.name == 'DATA_ENTRY':
            entry_string = self.current_token.value
            entry_match = re.match(DATA_ENTRY_REGEX, entry_string)

            address = int(entry_match.group(1))
            data_type = entry_match.group(2)
            operation = entry_match.group(3)
            data_string = entry_match.group(5)

            try:
                entry_data = parse_entry(data_type, operation, data_string)
            except G1ADataException as e:
                self.error(str(e))

            if address+len(entry_data) > self.meta_vars['memory']:
                self.error('Entry data size exceeds memory capacity. Consider allocating more memory.')
            
            self.data_entries.append(DataEntry(
                address, entry_data
            ))

        elif self.current_token.name == 'LABEL_NAME':
            self.state = AssemblerState.SUBROUTINES

        else:
            self.error(f'Expected data entry but got "{self.current_token.name}".')

    
    def assemble_subroutines(self):
        self.check_misplaced_meta_var()
        self.check_misplaced_data_entry()

        if self.current_token.name == 'LABEL_NAME':
            label_name = self.current_token.value[:-1]
            if label_name in self.labels:
                self.warning(f'Label "{label_name}" declared more than once.')
            else:
                self.labels[label_name] = self.instruction_index
        
        elif self.current_token.name == 'NAME':
            instruction_name = self.current_token.value
            if instruction_name not in INSTRUCTIONS:
                self.error(f'Unrecognized instruction "{instruction_name}".')

            instruction_arg_amount = ARGUMENT_COUNT_LOOKUP[instruction_name]
            instruction_args = self.get_until_newline()
            if len(instruction_args) != instruction_arg_amount:
                self.error(f'Expected {instruction_arg_amount} argument(s) for instruction "{instruction_name}" but got {len(instruction_args)}.')
            
            self.instructions.append(
                Instruction(
                    instruction_name, instruction_args, 
                    self.current_token.source_pos.lineno-1
                )
            )
            self.instruction_index += 1

        else:
            self.error(f'Expected label name or instruction name but got "{self.current_token.name}"')

    def assemble(self):
        try:
            for self.current_token in self.tokens:
                if self.current_token.name in {'NEWLINE', 'COMMENT'}:
                    continue

                if self.state == AssemblerState.META_VARS:
                    self.assemble_meta_vars()
                
                if self.state == AssemblerState.DATA:
                    self.assemble_data_entries()

                if self.state == AssemblerState.SUBROUTINES:
                    self.assemble_subroutines()
        
        except LexingError:
            self.error('Unrecognized token.')
        
        self.check_data_entry_spans()
        self.parse_instruction_args()

        # Check for start and tick labels
        if 'tick' in self.labels:
            self.tick_label = self.labels['tick']
        else:
            print(f'{COLOR_WARN}WARNING: "tick" label not found in program.{COLOR_RESET}')
        
        if 'start' in self.labels:
            self.start_label = self.labels['start']


    def assemble_json(self, include_source: bool) -> bytes:
        output_json = {
            'meta': self.meta_vars,
            'instructions': [i.to_json(include_source) for i in self.parsed_instructions]
        }

        if self.start_label != -1:
            output_json['start'] = self.start_label
        if self.tick_label != -1:
            output_json['tick'] = self.tick_label
        
        if self.data_entries:
            output_json['data'] = [e.to_json() for e in self.data_entries]
        
        if include_source:
            output_json['source'] = self.source_lines
        
        return json.dumps(output_json, separators=(',', ':')).encode('utf-8')

    
    def assemble_binary(self) -> bytes:
        file_dict = {
            'meta': self.meta_vars,
            'instruction_count': len(self.parsed_instructions),
            'start': self.start_label,
            'tick': self.tick_label
        }

        formatted_instructions = []
        for instruction in self.parsed_instructions:
            instruction_name = instruction.name
            arguments = instruction.arguments

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

        if self.data_entries:
            formatted_data_entries = []
            for entry in self.data_entries:
                address = entry.address
                data_values = entry.data
                formatted_data_entries.append({'address': address, 'size': len(data_values), 'values': data_values})
            
            file_dict['data_entry_count'] = len(formatted_data_entries)
            file_dict['data'] = formatted_data_entries
        else:
            file_dict['data_entry_count'] = 0
            file_dict['data'] = {}
        
        return G1BinaryFormat.build(file_dict)


def assemble(input_path: str, output_path: str, include_source: bool, output_format: OUTPUT_FORMATS):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'File "{input_path}" does not exist.')
    with open(input_path, 'r') as f:
        source_code = f.read()
    
    source_lines = source_code.split('\n')
    lexer = build_lexer()
    tokens = lexer.lex(source_code + '\n')

    assembler = Assembler(tokens, source_lines)
    assembler.assemble()

    # Set file content based on the output format
    if output_format == 'json':
        file_content = assembler.assemble_json(include_source)
    else:
        file_content = assembler.assemble_binary()
    
    # Write the output file
    with open(output_path, 'wb') as f:
        f.write(file_content)


def main():
    try:
        parser = argparse.ArgumentParser(description='Assemble a g1 program')
        parser.add_argument('input_path', help='The path to the input g1 assembly program')
        parser.add_argument('output_path', help='The path to the assembled g1 program')
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
    
    assemble(args.input_path, args.output_path, args.include_source, output_format)
    return 0


if __name__ == '__main__':
    sys.exit(main())
