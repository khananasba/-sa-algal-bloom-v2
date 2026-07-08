import zipfile
import os

base_dir = r"c:\Users\khana\Desktop\Ak_algal-bloom-monitor - Copy"
output_zip = os.path.join(base_dir, "deploy_aws.zip")

dirs_to_include = ["api", "algal_assistant", "data", "ml_engine", ".ebextensions"]
files_to_include = ["db_config.py", "requirements.txt", "Procfile"]

with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in files_to_include:
        full_path = os.path.join(base_dir, f)
        if os.path.exists(full_path):
            zf.write(full_path, f.replace('\\', '/'))
            print(f"Added: {f}")

    for d in dirs_to_include:
        full_dir = os.path.join(base_dir, d)
        if os.path.isdir(full_dir):
            for root, dirs, files in os.walk(full_dir):
                dirs[:] = [x for x in dirs if x not in ('__pycache__', 'venv', '.git')]
                for file in files:
                    if file.endswith(('.pyc', '.pyo')):
                        continue
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, base_dir).replace('\\', '/')
                    zf.write(full_path, arcname)
                    print(f"Added: {arcname}")

size_mb = os.path.getsize(output_zip) / 1024 / 1024
print(f"\nDone! ZIP size: {size_mb:.1f} MB — ready to upload to AWS")
