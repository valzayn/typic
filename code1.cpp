#include <iostream>

int add(int a, int b) {
    return a + b;
}

int main() {
    int x = 10;
    int y = 20;
    int z = add(x, y);

    if (z > 25) {
        int r = z * 2;
    } else {
        int r = z / 2;
    }

    int i = 0;
    while (i < 5) {
        i = i + 1;
    }

    return 0;
}