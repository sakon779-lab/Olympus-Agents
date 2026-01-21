# File: local_agent/tools/code_analysis.py
import ast
import os


def generate_skeleton(file_path: str) -> str:
    """
    อ่านไฟล์ Python แล้วคืนค่าเฉพาะ Class/Function Signature
    เพื่อประหยัด Token เวลาส่งให้ AI อ่าน (Strategy 1)
    """
    if not os.path.exists(file_path):
        return f"Error: File {file_path} not found."

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
        skeleton = []
        skeleton.append(f"# SKELETON OF: {file_path}")

        # เดินดูโครงสร้าง Code
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # ดึง Arguments: def my_func(a, b):
                args = [arg.arg for arg in node.args.args]
                # เช็ค Return Type Hint (ถ้ามี)
                returns = ""
                if node.returns:
                    returns = " -> ..."

                skeleton.append(f"Function: def {node.name}({', '.join(args)}){returns}: ...")

            elif isinstance(node, ast.ClassDef):
                # ได้แค่: class MyClass:
                bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                base_str = f"({', '.join(bases)})" if bases else ""
                skeleton.append(f"Class: class {node.name}{base_str}: ...")

        if not skeleton:
            return f"# File {file_path} is empty or contains no classes/functions."

        return "\n".join(skeleton)

    except Exception as e:
        return f"Error parsing {file_path}: {str(e)}"


# Test function (รันตรงๆ เพื่อทดสอบได้เลย)
if __name__ == "__main__":
    # ลองสร้างไฟล์ python ปลอมๆ มาเทส
    dummy_code = """
class PaymentProcessor:
    def process(self, amount: float, currency: str):
        print("Processing...")
        return True

def health_check():
    return "OK"
    """
    with open("temp_test.py", "w") as f:
        f.write(dummy_code)

    print(generate_skeleton("temp_test.py"))

    os.remove("temp_test.py")