"""
Allows external data to be attached to assembled g1 programs.
"""

import os
import re
from io import BytesIO 
from PIL import Image, UnidentifiedImageError


DATA_LINE_REGEX = r'^(\d+):\s*(\w+)\s+(\w+)\s+(.+)$'
HEX_REGEX = r'(:?[0-9a-fA-F]{2})+$'


class G1ADataException(Exception):
    """Base class for data parsing exceptions"""


def load_file(file_path: str) -> bytes:
    """
    Raises:
        G1ADataException: If the file was not found
    """
    if not os.path.isfile(file_path):
        raise G1ADataException(f'Could not find file "{file_path}".')

    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    return file_bytes


def load_bytes(bytes_hex: str) -> bytes:
    """
    Raises:
        G1ADataException: If the bytes are improperly formatted
    """

    if not re.match(HEX_REGEX, bytes_hex):
        raise G1ADataException('Expected hex value for byte data.')
    
    return bytes(bytes_hex)


def load_string(string: str) -> bytes:
    return bytes(string, 'ascii')


def image_operation(img_data: bytes) -> list[int]:
    """
    Raises:
        G1ADataException: If the operation failed
    """
    try:
        img = Image.open(BytesIO(img_data))
    except UnidentifiedImageError:
        raise G1ADataException('Could not parse bytes as an image.')
    
    result = [img.width, img.height]
    for i in range(img.height):
        for j in range(img.width):
            pixel = img.getpixel((j, i))
            pixel_int = pixel[2]
            pixel_int <<= 8
            pixel_int |= pixel[1]
            pixel_int <<= 8
            pixel_int |= pixel[0]
            result.append(pixel_int)
    return result


def raw_operation(data: bytes) -> list[int]:
    return list(data)


def pack_operation(data: bytes) -> list[int]:
    amount_padding = (4 - len(data) % 4) % 4
    data += b'0' * amount_padding
    
    result = []
    for i in range(0, len(data), 4):
        chunk = data[i:i+4]
        value = int.from_bytes(chunk, byteorder='big', signed=True)
        result.append(value)
    
    return result


def parse_entry(data_type: str, operation: str, data: str) -> list[int]:
    """
    Raises:
        G1ADataException: If a data parsing error occurs
    """

    load_result: bytes = b''
    if data_type == 'file':
        load_result = load_file(data)
    elif data_type == 'bytes':
        load_result = load_bytes(data)
    elif data_type == 'string':
        load_result = load_string(data)
    else:
        raise G1ADataException(f'Invalid data type "{data_type}".')

    data_bytes = load_result
    operation_result: list[int] = None
    if operation == 'raw':
        operation_result = raw_operation(data_bytes)
    elif operation == 'pack':
        operation_result = pack_operation(data_bytes)
    elif operation == 'img':
        operation_result = image_operation(data_bytes)
    else:
        raise G1ADataException(f'Invalid operation "{operation}".')
    
    # Insert length of string if necessary
    if data_type == 'string':
        operation_result.insert(0, len(operation_result))
    
    return operation_result
