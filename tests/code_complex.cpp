#include <iostream>

int arr[6];
int b[6] = {10, 20, 30, 40, 50, 60};

int sum_array(int n) {
    int total = 0;
    for (int i = 0; i < n; i = i + 1) {
        total = total + arr[i];
    }
    return total;
}

int max_array(int n) {
    int best = arr[0];
    int i = 1;
    while (i < n) {
        if (arr[i] > best) {
            best = arr[i];
        }
        i = i + 1;
    }
    return best;
}

int count_even(int n) {
    int cnt = 0;
    for (int i = 0; i < n; i = i + 1) {
        if (arr[i] % 2 == 0) {
            cnt = cnt + 1;
        }
    }
    return cnt;
}

void reverse_array(int n) {
    int i = 0;
    int j = n - 1;
    while (i < j) {
        int tmp = arr[i];
        arr[i] = arr[j];
        arr[j] = tmp;
        i = i + 1;
        j = j - 1;
    }
}

void bubble_sort(int n) {
    int i = 0;
    while (i < n) {
        int j = 0;
        while (j < n - 1 - i) {
            if (arr[j] > arr[j + 1]) {
                int tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
            }
            j = j + 1;
        }
        i = i + 1;
    }
}

int dot_product(int n) {
    int total = 0;
    for (int i = 0; i < n; i = i + 1) {
        total = total + arr[i] * b[i];
    }
    return total;
}

int main() {
    arr[0] = 42;
    arr[1] = 7;
    arr[2] = 19;
    arr[3] = 88;
    arr[4] = 3;
    arr[5] = 56;

    int s1 = sum_array(6);
    cout << s1 << endl;

    int mx = max_array(6);
    cout << mx << endl;

    int ev = count_even(6);
    cout << ev << endl;

    int dp = dot_product(6);
    cout << dp << endl;

    reverse_array(6);
    int s2 = sum_array(6);
    cout << s2 << endl;

    bubble_sort(6);
    int s3 = sum_array(6);
    cout << s3 << endl;

    int first = arr[0];
    int last = arr[5];
    cout << first << endl;
    cout << last << endl;

    int counter = 0;
    do {
        counter = counter + 1;
        if (counter % 2 == 0) {
            cout << counter << endl;
        }
    } while (counter < 5);

    int grand = s1 + s2 + s3 + mx + ev + dp;
    if (grand > 1000) {
        cout << "huge" << endl;
    } else if (grand > 500) {
        cout << "big" << endl;
    } else if (grand > 200) {
        cout << "medium" << endl;
    } else {
        cout << "small" << endl;
    }

    bool ok = true;
    if (ok && mx > 50 && first < 10) {
        cout << "range ok" << endl;
    } else {
        cout << "range bad" << endl;
    }

    int i = 0;
    int acc = 0;
    while (i < 6) {
        acc = acc + arr[i] * arr[i];
        i = i + 1;
    }
    cout << acc << endl;

    return 0;
}