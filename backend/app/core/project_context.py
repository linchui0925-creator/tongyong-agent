"""
ProjectContextManager - 项目上下文管理器

让 Agent 能够理解项目架构和代码结构
"""

import os
import re
from typing import Dict, List, Any, Optional
from pathlib import Path
import json

class ProjectContextManager:
    """项目上下文管理器"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.structure_cache = None
        self.cache_valid = False
    
    async def analyze_structure(self) -> Dict[str, Any]:
        """分析项目结构"""
        if self.cache_valid and self.structure_cache:
            return self.structure_cache
        
        structure = {
            'languages': self._detect_languages(),
            'frameworks': self._detect_frameworks(),
            'modules': await self._analyze_modules(),
            'dependencies': self._detect_dependencies(),
            'architecture': self._detect_architecture()
        }
        
        self.structure_cache = structure
        self.cache_valid = True
        
        return structure
    
    def _detect_languages(self) -> List[str]:
        """检测编程语言"""
        languages = []
        extensions = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.tsx': 'TypeScript React',
            '.jsx': 'JavaScript React',
            '.go': 'Go',
            '.rs': 'Rust',
            '.java': 'Java',
            '.cpp': 'C++',
            '.c': 'C',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.swift': 'Swift',
            '.kt': 'Kotlin'
        }
        
        for ext, lang in extensions.items():
            if list(self.project_root.rglob(f'*{ext}')):
                languages.append(lang)
        
        return languages
    
    def _detect_frameworks(self) -> List[Dict[str, str]]:
        """检测框架"""
        frameworks = []
        
        # Python 框架
        if (self.project_root / 'requirements.txt').exists():
            with open(self.project_root / 'requirements.txt') as f:
                content = f.read()
                if 'fastapi' in content.lower():
                    frameworks.append({'name': 'FastAPI', 'language': 'Python'})
                if 'flask' in content.lower():
                    frameworks.append({'name': 'Flask', 'language': 'Python'})
                if 'django' in content.lower():
                    frameworks.append({'name': 'Django', 'language': 'Python'})
        
        # Node.js 框架
        if (self.project_root / 'package.json').exists():
            with open(self.project_root / 'package.json') as f:
                content = f.read()
                if 'react' in content.lower():
                    frameworks.append({'name': 'React', 'language': 'JavaScript'})
                if 'vue' in content.lower():
                    frameworks.append({'name': 'Vue', 'language': 'JavaScript'})
                if 'next' in content.lower():
                    frameworks.append({'name': 'Next.js', 'language': 'JavaScript'})
        
        return frameworks
    
    async def _analyze_modules(self) -> List[Dict[str, Any]]:
        """分析项目模块"""
        modules = []
        
        # Python 模块
        backend_path = self.project_root / 'backend'
        if backend_path.exists():
            modules.append({
                'name': 'backend',
                'path': 'backend/',
                'language': 'Python',
                'structure': self._analyze_python_structure(backend_path)
            })
        
        # Frontend 模块
        frontend_path = self.project_root / 'frontend'
        if frontend_path.exists():
            modules.append({
                'name': 'frontend',
                'path': 'frontend/',
                'language': 'TypeScript',
                'structure': self._analyze_react_structure(frontend_path)
            })
        
        return modules
    
    def _analyze_python_structure(self, path: Path) -> Dict[str, Any]:
        """分析 Python 项目结构"""
        structure = {
            'directories': [],
            'files': []
        }
        
        for item in path.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                structure['directories'].append(item.name)
                structure['files'].append({
                    'name': item.name,
                    'type': 'directory'
                })
            elif item.is_file() and item.suffix == '.py':
                structure['files'].append({
                    'name': item.name,
                    'type': 'file'
                })
        
        # 深度分析 app 目录
        app_path = path / 'app'
        if app_path.exists():
            structure['app_structure'] = self._deep_analyze_app_structure(app_path)
        
        return structure
    
    def _deep_analyze_app_structure(self, app_path: Path) -> Dict[str, Any]:
        """深度分析 app 目录结构"""
        structure = {
            'modules': [],
            'api_routes': [],
            'core_modules': []
        }
        
        for item in app_path.iterdir():
            if item.is_dir():
                structure['modules'].append(item.name)
                
                # 检查 API 路由
                if item.name == 'api':
                    for route_file in item.glob('*.py'):
                        if route_file.name != '__init__.py':
                            structure['api_routes'].append(route_file.stem)
                
                # 检查核心模块
                if item.name == 'core':
                    for core_file in item.glob('*.py'):
                        if core_file.name != '__init__.py':
                            structure['core_modules'].append(core_file.stem)
        
        return structure
    
    def _analyze_react_structure(self, path: Path) -> Dict[str, Any]:
        """分析 React 项目结构"""
        structure = {
            'directories': [],
            'files': []
        }
        
        src_path = path / 'src'
        if src_path.exists():
            for item in src_path.iterdir():
                if item.is_dir():
                    structure['directories'].append(item.name)
                    
                    # 检查组件
                    if item.name == 'components':
                        structure['components'] = self._analyze_components(item)
                    elif item.name == 'pages':
                        structure['pages'] = self._analyze_pages(item)
        
        return structure
    
    def _analyze_components(self, components_path: Path) -> List[str]:
        """分析组件结构"""
        components = []
        for item in components_path.rglob('*.tsx'):
            if item.name != 'index.tsx':
                components.append(str(item.relative_to(components_path)))
        return components
    
    def _analyze_pages(self, pages_path: Path) -> List[str]:
        """分析页面结构"""
        pages = []
        for item in pages_path.rglob('*.tsx'):
            pages.append(str(item.relative_to(pages_path)))
        return pages
    
    def _detect_dependencies(self) -> Dict[str, Any]:
        """检测依赖关系"""
        dependencies = {}
        
        # Python 依赖
        req_file = self.project_root / 'requirements.txt'
        if req_file.exists():
            with open(req_file) as f:
                dependencies['python'] = [
                    line.strip() for line in f 
                    if line.strip() and not line.startswith('#')
                ]
        
        # Node.js 依赖
        pkg_file = self.project_root / 'package.json'
        if pkg_file.exists():
            with open(pkg_file) as f:
                pkg = json.load(f)
                dependencies['node'] = {
                    'dependencies': pkg.get('dependencies', {}),
                    'devDependencies': pkg.get('devDependencies', {})
                }
        
        return dependencies
    
    def _detect_architecture(self) -> str:
        """检测架构模式"""
        architectures = []
        
        # 检测前后端分离
        if (self.project_root / 'backend').exists() and (self.project_root / 'frontend').exists():
            architectures.append('前后端分离 (BFF)')
        
        # 检测微服务
        if len(list(self.project_root.glob('services/*'))) > 0:
            architectures.append('微服务')
        
        # 检测 MVC
        backend_app = self.project_root / 'backend' / 'app'
        if backend_app.exists():
            if (backend_app / 'models') and (backend_app / 'views') and (backend_app / 'controllers'):
                architectures.append('MVC')
            elif (backend_app / 'api') and (backend_app / 'core'):
                architectures.append('分层架构')
        
        return ', '.join(architectures) if architectures else '单体应用'
    
    async def get_file_content(self, file_path: str) -> Optional[str]:
        """获取文件内容"""
        full_path = self.project_root / file_path
        
        if not full_path.exists() or not full_path.is_file():
            return None
        
        try:
            # 只读取小文件（小于 100KB）
            if full_path.stat().st_size > 100 * 1024:
                return f"文件过大 ({full_path.stat().st_size / 1024:.1f}KB)，跳过"
            
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None
    
    async def search_code(self, pattern: str) -> List[Dict[str, Any]]:
        """搜索代码"""
        results = []
        
        # 搜索常见代码文件
        code_extensions = ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java']
        
        for ext in code_extensions:
            for file_path in self.project_root.rglob(f'*{ext}'):
                # 跳过 node_modules 和 __pycache__
                if 'node_modules' in str(file_path) or '__pycache__' in str(file_path):
                    continue
                
                try:
                    if file_path.stat().st_size > 100 * 1024:  # 跳过大文件
                        continue
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        if pattern.lower() in content.lower():
                            # 找到匹配的行
                            lines = content.split('\n')
                            matched_lines = [
                                (i+1, line) for i, line in enumerate(lines)
                                if pattern.lower() in line.lower()
                            ]
                            
                            results.append({
                                'file': str(file_path.relative_to(self.project_root)),
                                'matches': matched_lines[:10],  # 最多返回10个匹配
                                'total_matches': len([l for l in lines if pattern.lower() in l.lower()])
                            })
                except Exception:
                    continue
        
        return results
    
    def invalidate_cache(self):
        """使缓存失效"""
        self.cache_valid = False
        self.structure_cache = None
