import os

def count_lines_of_code(directory, file_extensions, exclude_dirs):
    total_lines = 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]  # Skip excluded directories
        for file in files:
            if file.endswith(file_extensions):
                with open(os.path.join(root, file), 'r', encoding='utf-8', errors='ignore') as f:
                    total_lines += sum(1 for _ in f)
    return total_lines

directory = '.'  # Change this to your project directory
file_extensions = ('.py', '.html', '.js')  # Add other file extensions if needed
exclude_dirs = ['node_modules', '.venv']
total_lines = count_lines_of_code(directory, file_extensions, exclude_dirs)
print(f'Total lines of code: {total_lines}')
