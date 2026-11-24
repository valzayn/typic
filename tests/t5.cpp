#include <iostream>
using namespace std;

int main() {
    int a[5] = {1, 2, 3, 4, 5};
    int s = 0;
    for (int i = 0; i < 5; i = i + 1) {
        s = s + a[i];
    }
    cout << s << endl;
    return 0;
}
