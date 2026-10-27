# -*- coding: utf-8 -*-
# Сгенерировано транслятором C++ -> Python

# #include <iostream> -> встроенный print()
def main():
    i = 0
    n = 0
    is_prime = True
    print("Enter a positive integer: ", end='')
    n = 3
    if n == 0 or n == 1:
        is_prime = False
    i = 2
    while i <= n / 2:
        if n % i == 0:
            is_prime = False
            break
    if is_prime:
        print(n, " is a prime number", end='')
    else:
        print(n, " is not a prime number", end='')
    return 0

if __name__ == "__main__":
    main()