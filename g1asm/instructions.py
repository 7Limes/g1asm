INSTRUCTIONS = ['mov', 'movp', 'add', 'sub', 'mul', 'div', 'mod', 'less', 'equal', 'not', 'jmp', 'color', 'point', 'line', 'rect', 'log', 'getp', 'setch']
ARGUMENT_COUNTS = [2, 2, 3, 3, 3, 3, 3, 3, 3, 2, 2, 3, 2, 4, 4, 1, 3, 4]
ARGUMENT_COUNT_LOOKUP = {i: c for i, c in zip(INSTRUCTIONS, ARGUMENT_COUNTS)}
ASSIGNMENT_INSTRUCTIONS = {'mov', 'movp', 'add', 'sub', 'mul', 'div', 'mod', 'less', 'equal', 'not', 'getp'}
