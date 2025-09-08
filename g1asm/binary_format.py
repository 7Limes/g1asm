from construct import Struct, Const, Int32ub, Int32sb, Int16ub, Int8ub, Array, this, Computed
from g1asm.instructions import INSTRUCTIONS, ARGUMENT_COUNTS


OPCODE_LOOKUP = {ins: i for i, ins in enumerate(INSTRUCTIONS)}
SIGNATURE = b'g1'

ARG_TYPE_LITERAL = 0
ARG_TYPE_ADDRESS = 1


G1Argument = Struct(
    'type' / Int8ub,
    'value' / Int32sb
)


G1Instruction = Struct(
    'opcode' / Int8ub,
    'argument_count' / Computed(lambda ctx: ARGUMENT_COUNTS[ctx.opcode]),
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
