#include <iostream>

int square(int n) {
    return n * n;
}

int main() {
    int sum = 0;

    for (int i = 1; i <= 5; i = i + 1) {
        sum = sum + square(i);
    }

    cout << sum << endl;

    int count = 0;
    do {
        count = count + 1;
    } while (count < 3);

    if (sum > 50) {
        cout << "big" << endl;
    } else if (sum > 20) {
        cout << "medium" << endl;
    } else {
        cout << "small" << endl;
    }

    return 0;
}