"""
Tool para gerar a árvore de diretórios do projeto, ignorando pastas irrelevantes, e salvar em um arquivo Markdown.
"""
import os

def run(output_file="project_structure.md"):
    ignored_dirs = {'.git', '__pycache__', 'venv', '.venv', '.idea', '.vscode', 'node_modules'}
    
    def walk_dir(root_dir, prefix=""):
        tree = []
        try:
            items = sorted(os.listdir(root_dir))
        except PermissionError:
            return []
            
        filtered_items = [i for i in items if i not in ignored_dirs and not i.startswith('.')] 
        
        for i, item in enumerate(filtered_items):
            path = os.path.join(root_dir, item)
            is_last = (i == len(filtered_items) - 1)
            connector = "└── " if is_last else "├── "
            
            tree.append(f"{prefix}{connector}{item}")
            
            if os.path.isdir(path):
                extension = "    " if is_last else "│   "
                tree.extend(walk_dir(path, prefix + extension))
        return tree

    structure = walk_dir(os.getcwd())
    content = "# Project Structure\n\n```\n" + "\n".join(structure) + "\n```"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
    
    return f"Estrutura do projeto salva com sucesso em {output_file}"