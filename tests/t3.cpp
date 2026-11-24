#include <iostream>
using namespace std;

int main() {
    int x = 15;
    if (x > 20) {
        cout << "big" << endl;
    } else if (x > 10) {
        cout << "mid" << endl;
    } else {
        cout << "small" << endl;
    }
    return 0;
}
