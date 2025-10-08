"""
Allows external data to be attached to assembled g1 programs via g1d files.
"""

import os
import re
from io import BytesIO 
from PIL import Image, UnidentifiedImageError


DATA_LINE_REGEX = r'^(\d+):\s*(\w+)\s+(\w+)\s+(.+)$'
HEX_REGEX = r'(:?[0-9a-fA-F]{2})+$'


def error(line_number: str, message: str):
    print(f'DATA ERROR: Line {line_number+1}: {message}')


# returns True if succeeded, False otherwise
def add_data_entry(parsed_data: list, memory_size: int, line_number: int, entry: tuple[int, list[int]]) -> bool:
    address, numbers = entry
    if address+len(numbers) > memory_size:
        error(line_number, 'Entry data size exceeds memory capacity. Consider allocating more memory.')
        return False
    parsed_data.append(entry)
    return True


def load_file(file_path: str) -> bytes | str:
    if not os.path.isfile(file_path):
        return f'Could not find file "{file_path}".'

    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    return file_bytes


def load_bytes(bytes_hex: str) -> bytes | str:
    if not re.match(HEX_REGEX, bytes_hex):
        return 'Expected hex value for byte data.'
    
    return bytes(bytes_hex)


def load_string(string: str) -> bytes:
    return bytes(string, 'ascii')


def image_operation(img_data: bytes) -> list[int] | str:
    try:
        img = Image.open(BytesIO(img_data))
    except UnidentifiedImageError:
        return 'Could not parse bytes as an image.'
    
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


def parse_entry(data_type: str, operation: str, data: str) -> list[int] | str:
    load_result: bytes | str = b''
    if data_type == 'file':
        load_result = load_file(data)
    elif data_type == 'bytes':
        load_result = load_bytes(data)
    elif data_type == 'string':
        load_result = load_string(data)
    else:
        return f'Invalid data type "{data_type}".'
    
    if isinstance(load_result, str):
        return load_result

    data_bytes = load_result
    operation_result: list[int] = None
    if operation == 'raw':
        operation_result = raw_operation(data_bytes)
    elif operation == 'pack':
        operation_result = pack_operation(data_bytes)
    elif operation == 'img':
        operation_result = image_operation(data_bytes)
    else:
        return f'Invalid operation "{operation}".'
    
    if isinstance(operation_result, str):
        return operation_result
    
    # Insert length of string if necessary
    if data_type == 'string':
        operation_result.insert(0, len(operation_result))
    
    return operation_result


def parse_data(data_entries: str, memory_size: int) -> list[tuple[int, list[int]]] | None:
    pattern = re.compile(DATA_LINE_REGEX);
    parsed_data = []
    for line_number, line in enumerate(data_entries.split('\n')):
        m = pattern.match(line)
        if not m:
            error(line_number, 'Expected [address]: [data type] [operation] syntax for data entry.')
            return None

        address = int(m.group(1))
        data_type = m.group(2)
        operation = m.group(3)
        data = m.group(4)
        parse_entry_result = parse_entry(data_type, operation, data)

        if isinstance(parse_entry_result, str):
            error(line_number, parse_entry_result)

        added = add_data_entry(parsed_data, memory_size, line_number, (address, parse_entry_result))
        if not added:
            return None

    spans = [[a, a+len(data)-1] for a, data in parsed_data]
    spans.sort(key=lambda x: x[0])
    for i in range(len(spans)-1):
        for j in range(i+1, len(spans)):
            if spans[i][1] >= spans[j][0]:
                print(f'WARNING: Data overlap found between {spans[i]} and {spans[j]}.')
    
    return parsed_data
