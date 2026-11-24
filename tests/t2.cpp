#include <iostream>
using namespace std;

int main() {
    int i = 1;
    int s = 0;
    while (i <= 10) {
        s = s + i;
        i = i + 1;
    }
    cout << s << endl;
    return 0;
}
