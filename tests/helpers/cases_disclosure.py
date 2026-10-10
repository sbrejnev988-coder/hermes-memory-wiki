"""Existing SOURCE AST selector, transplanted without behavioral changes.
No package import or SDK/native authority.
"""
def closure(tree, names, namespace, *, methods=()):
    defs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    assignments={t.id:n for n in tree.body if isinstance(n,(ast.Assign,ast.AnnAssign))
                 for t in (n.targets if isinstance(n,ast.Assign) else [n.target]) if isinstance(t,ast.Name)}
    selected={};pending=list(names)
    for method in methods:
        pending += [n.id for n in ast.walk(method) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)]
    while pending:
        name=pending.pop()
        if name in selected or name in namespace:continue
        node=defs.get(name) or assignments.get(name)
        if node is None:continue
        selected[name]=node
        pending += [n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)]
    ordered=[n for n in tree.body if n in selected.values()]
    if methods:
        node=ast.ClassDef(name='MemoryWikiProvider',bases=[],keywords=[],body=list(methods),decorator_list=[],type_params=[])
        ordered.append(ast.copy_location(node,CLASS))
    module=ast.fix_missing_locations(ast.Module(body=ordered,type_ignores=[]))
    exec(compile(module,namespace['__file__'],'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True),namespace)
    return sorted(selected)
