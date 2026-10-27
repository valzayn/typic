from lec_an import tokens, Parser
from semantic import SemanticAnalyzer
from codegen_py import PythonCodeGenerator  # Python


def main():
    print("=" * 60)
    print("ТОКЕНЫ:")
    print("=" * 60)
    for i, t in enumerate(tokens):
        print(f"{i:3d}: {t}")

    parser = Parser(tokens)
    tree = parser.parse()

    print("\n" + "=" * 60)
    print("СИНТАКСИЧЕСКОЕ ДЕРЕВО:")
    print("=" * 60)
    tree.print()

    print("\n" + "=" * 60)
    print("СЕМАНТИЧЕСКИЙ АНАЛИЗ:")
    print("=" * 60)

    sem = SemanticAnalyzer()
    errors = sem.analyze(tree)

    if errors:
        print("✗ Обнаружены семантические ошибки:")
        for e in errors:
            print(f"   • {e}")
        print("\nГенерация кода пропущена из-за ошибок.")
        return

    print("✓ Семантических ошибок не найдено.")

    # --- Python ---
    print("\n" + "=" * 60)
    print("СГЕНЕРИРОВАННЫЙ PYTHON-КОД:")
    print("=" * 60)
    py_code = PythonCodeGenerator().generate(tree, sem.table)
    print(py_code)

    # сохранить в файл
    with open("out.py", "w", encoding="utf-8") as f:
        f.write(py_code)
    print("\n✓ Python-код сохранён в out.py")


if __name__ == "__main__":
    main()