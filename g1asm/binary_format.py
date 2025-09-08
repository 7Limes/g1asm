from construct import Struct, Const, Int32ub, Int32sb, Int16ub, Int8ub, Array, this, Computed
from typing import Any
from construct.lib import Container, ListContainer
from io import BytesIO

from g1.instructions.instructions import INSTRUCTIONS, ARGUMENT_COUNTS


INSTRUCTION_IDS = {ins: i for i, ins in enumerate(INSTRUCTIONS)}
SIGNATURE = b'g1'

ARG_TYPE_LITERAL = 0
ARG_TYPE_ADDRESS = 1


G1Argument = Struct(
    'type' / Int8ub,
    'value' / Int32sb
)


G1Instruction = Struct(
    'id' / Int8ub,
    'argument_count' / Computed(lambda ctx: ARGUMENT_COUNTS[ctx.id]),
    'arguments' / Array(this.argument_count, G1Argument)
)


G1DataEntry = Struct(
    'address' / Int32ub,
    'size' / Int32ub,
    'values' / Array(this.size, Int32sb)
)


G1BinaryFormat = Struct(
    'signature' / Const(SIGNATURE),
    'meta' / Struct(
        'memory' / Int32ub,
        'width' / Int16ub,
        'height' / Int16ub,
        'tickrate' / Int16ub
    ),
    'tick' / Int32sb,
    'start' / Int32sb,
    'instruction_count' / Int32ub,
    'instructions' / Array(this.instruction_count, G1Instruction),
    'data_entry_count' / Int32ub,
    'data' / Array(this.data_entry_count, G1DataEntry)
)


def format_json(program_json: dict):
    """
    Converts a program JSON into one that can be parsed into a binary.
    """
    output_json = program_json.copy()
    output_json['instruction_count'] = len(program_json['instructions'])
    output_json.setdefault('start', -1)
    output_json.setdefault('tick', -1)

    verbose_instructions = []
    for instruction_data in program_json['instructions']:
        instruction_name, arguments = instruction_data[:2]  # only grab the first 2 in case of debug mode
        verbose_arguments = []
        for argument in arguments:
            if isinstance(argument, int):
                verbose_arguments.append({'type': ARG_TYPE_LITERAL, 'value': argument})
            else:
                verbose_arguments.append({'type': ARG_TYPE_ADDRESS, 'value': int(argument[1:])})
        instruction_id = INSTRUCTION_IDS[instruction_name]
        verbose_instruction = {
            'id': instruction_id,
            'arguments': verbose_arguments
        }
        verbose_instructions.append(verbose_instruction)
    output_json['instructions'] = verbose_instructions

    if 'data' in program_json:
        verbose_data_entries = []
        for address, data_values in program_json['data']:
            verbose_data_entries.append({'address': address, 'size': len(data_values), 'values': data_values})
        output_json['data_entry_count'] = len(verbose_data_entries)
        output_json['data'] = verbose_data_entries
    else:
        output_json['data_entry_count'] = 0
        output_json['data'] = {}

    return output_json

