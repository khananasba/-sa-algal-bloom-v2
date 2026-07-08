import shutil
import os
import subprocess

src_file = r'frontend/sa-bloom-dashboard/src/App.js'
dest_file = r'c:\Users\khana\Desktop\algal-bloom-monitor\frontend\sa-bloom-dashboard\src\App.js'

if os.path.exists(dest_file):
    shutil.copy2(src_file, dest_file)
    print('Copied App.js to algal-bloom-monitor')
    
    # Commit and push main repo
    cwd = r'c:\Users\khana\Desktop\algal-bloom-monitor'
    subprocess.run('git add -A', shell=True, cwd=cwd)
    subprocess.run(['git', 'commit', '-m', 'Frontend: update feedback text in navbar'], cwd=cwd)
    subprocess.run(['git', 'push', 'origin', 'main'], cwd=cwd)
    print('Pushed main repository successfully!')

# Commit and push copy repo
cwd_copy = r'c:\Users\khana\Desktop\Ak_algal-bloom-monitor - Copy'
subprocess.run('git add -A', shell=True, cwd=cwd_copy)
subprocess.run(['git', 'commit', '-m', 'Frontend: update feedback text in navbar'], cwd=cwd_copy)
subprocess.run(['git', 'push', 'origin', 'main'], cwd=cwd_copy)
print('Pushed copy repository successfully!')
