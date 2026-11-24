#include <iostream>
using namespace std;

int main() {
    int d = 2;
    switch (d) {
        case 1:
            cout << "one" << endl;
            break;
        case 2:
            cout << "two" << endl;
            break;
        default:
            cout << "other" << endl;
    }
    return 0;
}
