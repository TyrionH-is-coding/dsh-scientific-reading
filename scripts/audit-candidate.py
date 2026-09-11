"""核对候选 npm 包及内置 wheel 与工作树的文件集合、字节和 SHA。"""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

root, archive, output = (Path(value).resolve() for value in sys.argv[1:4])
digest = lambda data: hashlib.sha256(data).hexdigest()
with tarfile.open(archive) as package:
    files = {}
    wheel = None
    for member in package.getmembers():
        if not member.isfile():
            continue
        relative = Path(member.name).relative_to('package')
        source = (root / relative).resolve()
        assert source.is_relative_to(root), member.name
        data = package.extractfile(member).read()
        assert data == source.read_bytes(), str(relative)
        files[relative.as_posix()] = digest(data)
        if relative.suffix == '.whl':
            assert wheel is None
            wheel = data
    assert {'lib/reader-client.js', 'lib/reader-client.css', 'lib/model_policy.js', 'lib/reader_chat.js'} <= files.keys()
    assert wheel is not None
with zipfile.ZipFile(io.BytesIO(wheel)) as package:
    python_files = {name: hashlib.sha256(package.read(name)).hexdigest() for name in package.namelist() if name.endswith('.py')}
    sources = {}
    for folder, parent in ((root / 'engine/src/scientific_reading', root / 'engine/src'),
                           (root / 'engine/reader', root / 'engine')):
        for file in folder.rglob('*.py'):
            sources[file.relative_to(parent).as_posix()] = digest(file.read_bytes())
    assert python_files == sources
report = {'passed': True, 'version': json.loads((root / 'package.json').read_text(encoding='utf-8'))['version'],
          'archive': archive.name, 'sha256': digest(archive.read_bytes()), 'python_file_count': len(sources),
          'package_file_count': len(files), 'all_packaged_files_match_current_source': True,
          'python_files': python_files, 'package_files': files}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in report.items() if key not in {'python_files', 'package_files'}}))
