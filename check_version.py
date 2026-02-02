import pip

# 检查 notion-client 版本
packages = pip.get_installed_distributions()
for pkg in packages:
    if 'notion' in pkg.project_name.lower():
        print(f"{pkg.project_name}: {pkg.version}")
