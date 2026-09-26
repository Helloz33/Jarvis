def calculator():
    while True:
        symbol = input('Enter an operation (add, subtract, multiply, divide) or type quit to exit: ')
        if symbol == 'quit':
            print('Exiting calculator.')
            break
        num1 = float(input('Enter number 1: '))
        num2 = float(input('Enter number 2: '))
        if symbol == 'add':
            print('Result:', num1 + num2)
        elif symbol == 'subtract':
            print('Result:', num1 - num2)
        elif symbol == 'multiply':
            print('Result:', num1 * num2)
        elif symbol == 'divide':
            if num2 != 0:
                print('Result:', num1 / num2)
            else:
                print('Error: Division by zero')
        else:
            print('Invalid operation. Please try again.')

calculator()