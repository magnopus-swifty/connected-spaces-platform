from copy import deepcopy
from pathlib import Path
from shutil import rmtree
from typing import Dict, List, Union, Any

import subprocess
import chevron
import os
import sys

from Config import config
from MetadataTypes import (
    EnumMetadata,
    StructMetadata,
    FunctionMetadata,
    ClassMetadata,
    TemplateMetadata,
    TypeMetadata,
    InterfaceMetadata,
)
from Parser import read_whole_file, error_in_file, warning_in_file


class CSharpWrapperGenerator:
    __TEMPLATE_DIRECTORY = config["template_directory"] + "CSharp/"
    __PARTIALS_DIRECTORY = __TEMPLATE_DIRECTORY + "Partials/"
    __OUTPUT_DIRECTORY = config["output_directory"] + "CSharp/"
    __BASE_NAMESPACE = "Csp"

    __NAMESPACE_TRANSLATIONS = {
        "csp": __BASE_NAMESPACE,
        "common": "Common",
        "memory": "Memory",
        "multiplayer": "Multiplayer",
        "systems": "Systems",
        "web": "Web",
    }

    def __translate_namespace(self, obj: Any) -> None:
        if obj.namespace == None:
            obj.translated_namespace = None

            return

        namespaces = obj.namespace.split("::")

        for i in range(0, min(2, len(namespaces))):
            if namespaces[i] in self.__NAMESPACE_TRANSLATIONS:
                namespaces[i] = self.__NAMESPACE_TRANSLATIONS[namespaces[i]]

        obj.translated_namespace = ".".join(namespaces)

    def __translate_enum_base(self, obj: EnumMetadata) -> None:
        t = obj.base

        if t == "uint8_t" or t == "unsigned char":
            obj.base = "byte"
        elif t == "uint16_t" or t == "unsigned short":
            obj.base = "ushort"

    def __translate_type(self, obj: TypeMetadata) -> None:
        self.__translate_namespace(obj)

        if obj.is_template:
            assert obj.template_arguments is not None

            for ta in obj.template_arguments:
                self.__translate_type(ta.type)

        t = obj.name

        if not hasattr(obj, "is_void_pointer"):
            obj.is_void_pointer = False

        if t == "int8_t":
            obj.name = "sbyte"
        elif t == "uint8_t" or t == "unsigned char":
            obj.name = "byte"
        elif t == "int16_t":
            obj.name = "short"
        elif t == "uint16_t":
            obj.name = "ushort"
        elif t == "int32_t" or t == "long":
            obj.name = "int"
        elif t == "uint32_t" or t == "unsigned int" or t == "unsigned long":
            obj.name = "uint"
        elif t == "int64_t" or t == "long long" or t == "long int":
            obj.name = "long"
        elif t == "uint64_t" or t == "unsigned long long" or t == "unsigned long int":
            obj.name = "ulong"
        elif t == "size_t":
            # Assume 64-bit only for now
            obj.name = "ulong"
        elif t == "String":
            obj.name = "string"
            obj.namespace = None
            obj.translated_namespace = None
            obj.is_pointer = False
            obj.is_reference = False
            obj.is_pointer_or_reference = False
        elif (t == "void" or t == "char") and obj.is_pointer:
            obj.name = "IntPtr"
            obj.is_pointer = False
            obj.is_reference = False
            obj.is_pointer_or_reference = False
            obj.is_void_pointer = True
            obj.translated_namespace = None

    def __translate_comments(self, comments: List[str]) -> None:
        """Rewrite a list of comments from Javadoc-style to C# XML style"""
        if comments is None:
            return

        for i in range(len(comments)):
            comment = comments[i]
            comment = comment.replace("<", "&lt;").replace(">", "&gt;")

            if comment[0] != "@":
                comments[i] = f"<remarks>{comment}</remarks>"
                continue

            index = comment.find(" ")
            tag = comment[:index]
            content = comment[index + 1 :]

            if tag == "@brief":
                comments[i] = f"<summary>{content}</summary>"
            elif tag == "@return":
                index = content.find(":")

                while content[index + 1] == ":":
                    index = content.find(":", index + 2)

                content = content[index + 1 :].lstrip()

                if content[0].islower():
                    content = content.capitalize()

                comments[i] = f"<returns>{content}</returns>"
            elif tag == "@param":
                index = content.find(" ")
                var_name = content[:index]
                content = content[index + 1 :].lstrip()

                index = content.find(":")

                while content[index + 1] == ":":
                    index = content.find(":", index + 2)

                content = content[index + 1 :].lstrip()

                if content[0].islower():
                    content = content.capitalize()

                comments[i] = f'<param name="{var_name}">{content}</param>'
            elif tag == "@note":
                comments[i] = f"<remarks>{content}</remarks>"

    def __class_derives_from(
        self, obj: ClassMetadata, base_namespace: str, base_name: str, classes: Dict[str, ClassMetadata]
    ) -> bool:
        if obj.base == None:
            return False

        if obj.base.namespace == base_namespace and obj.base.name == base_name:
            return True

        full_type_name = f"{obj.base.namespace}::{obj.base.name}"

        if not full_type_name in classes:
            return False

        base_class = classes[full_type_name]

        return self.__class_derives_from(base_class, base_namespace, base_name, classes)

    def __get_file_output_directory(
        self, obj: Union[EnumMetadata, StructMetadata, InterfaceMetadata, ClassMetadata, TemplateMetadata]
    ):
        header_file: str

        if isinstance(obj, TemplateMetadata):
            header_file = obj.definition.header_file
        else:
            header_file = obj.header_file

        out_path = header_file.split("/")
        out_path = out_path[1:-1]

        return "/".join(out_path)

    def generate(
        self,
        enums: Dict[str, EnumMetadata],
        structs: Dict[str, StructMetadata],
        functions: Dict[str, FunctionMetadata],
        classes: Dict[str, ClassMetadata],
        templates: Dict[str, TemplateMetadata],
        interfaces: Dict[str, InterfaceMetadata],
    ) -> None:
        # Deepcopy all metadata so we don't modify the original data for any wrapper generator classes that get called after this one
        self.enums = deepcopy(enums)
        self.structs = deepcopy(structs)
        self.functions = deepcopy(functions)
        self.classes = deepcopy(classes)
        self.templates = deepcopy(templates)
        self.interfaces = deepcopy(interfaces)

        out_path = Path(self.__OUTPUT_DIRECTORY)

        # Remove the output directory first to delete all previously generated code
        if out_path.exists():
            rmtree(out_path)

        # Recreate the output directory
        out_path.mkdir(parents=True, exist_ok=True)

        enum_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "Enum.mustache")
        struct_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "Struct.mustache")
        global_functions_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "GlobalFunctions.mustache")
        class_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "Class.mustache")
        interface_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "Interface.mustache")
        templateclass_template = read_whole_file(self.__TEMPLATE_DIRECTORY + "Template.mustache")

        self.translate_functions(self.functions)

        self.render_enums(enum_template)
        self.render_structs(struct_template)
        self.render_global_functions(global_functions_template)
        self.render_interfaces(interface_template)
        self.render_classes(class_template)
        self.render_templates(templateclass_template)

        self.format_output()

    def format_output(self):
        """Format output with CSharpier"""
        scriptDirectory = os.path.dirname(os.path.realpath(__file__))
        subprocess.run(
            f'"{ scriptDirectory }\\Formatters\\CSharpier\\dotnet-csharpier.exe" "{self.__OUTPUT_DIRECTORY}"',
            shell=True,
        )

    def translate_functions(self, functions) -> None:
        for f in functions.values():
            self.__translate_comments(f.doc_comments)

            if f.return_type != None:
                self.__translate_type(f.return_type)

            if f.parameters is not None:
                for p in f.parameters:
                    self.__translate_type(p.type)

                    if p.type.is_function_signature:
                        assert p.type.function_signature is not None

                        if p.type.function_signature.parameters is not None:
                            for fp in p.type.function_signature.parameters:
                                self.__translate_type(fp.type)

    def render_enums(self, enum_template) -> None:
        for e in self.enums.values():
            surrounding_types = None

            if e.is_nested_type:
                surrounding_types = e.namespace[e.namespace.find("::") + 2 :].split("::")
                e.namespace = e.namespace[: e.namespace.find("::")]

            if e.doc_comments is not None:
                self.__translate_comments(e.doc_comments)

            self.__translate_namespace(e)
            self.__translate_enum_base(e)
            subdir = self.__get_file_output_directory(e)

            if surrounding_types != None:
                for st in surrounding_types:
                    subdir = f"{subdir}/{st}"

            e.surrounding_types = surrounding_types

            for f in e.fields:
                if f.doc_comments is not None:
                    self.__translate_comments(f.doc_comments)

            Path(self.__OUTPUT_DIRECTORY + subdir).mkdir(parents=True, exist_ok=True)

            with open(f"{self.__OUTPUT_DIRECTORY}{subdir}/{e.name}.cs", "w") as f:
                print(
                    chevron.render(
                        enum_template, {"data": e, "extra_data": config}, self.__PARTIALS_DIRECTORY, warn=True
                    ),
                    file=f,
                )

    def render_structs(self, struct_template) -> None:
        for s in self.structs.values():
            surrounding_types = None

            if s.is_nested_type:
                surrounding_types = s.namespace[s.namespace.find("::") + 2 :].split("::")
                s.namespace = s.namespace[: s.namespace.find("::")]

            self.__translate_comments(s.doc_comments)
            self.__translate_namespace(s)
            subdir = self.__get_file_output_directory(s)

            if surrounding_types != None:
                for st in surrounding_types:
                    subdir = f"{subdir}/{st}"

            s.surrounding_types = surrounding_types

            Path(self.__OUTPUT_DIRECTORY + subdir).mkdir(parents=True, exist_ok=True)

            with open(f"{self.__OUTPUT_DIRECTORY}{subdir}/{s.name}.cs", "w") as f:
                print(
                    chevron.render(
                        struct_template, {"data": s, "extra_data": config}, self.__PARTIALS_DIRECTORY, warn=True
                    ),
                    file=f,
                )

    def render_global_functions(self, global_functions_template) -> None:
        with open(f"{self.__OUTPUT_DIRECTORY}Csp.cs", "w") as f:
            print(
                chevron.render(
                    global_functions_template,
                    {"data": list(self.functions.values()), "extra_data": config},
                    self.__PARTIALS_DIRECTORY,
                    warn=True,
                ),
                file=f,
            )

    def render_interfaces(self, interface_template) -> None:
        for i in self.interfaces.values():
            surrounding_types = None

            if i.is_nested_type:
                surrounding_types = i.namespace[i.namespace.find("::") + 2 :].split("::")
                i.namespace = i.namespace[: i.namespace.find("::")]

            self.__translate_comments(i.doc_comments)
            self.__translate_namespace(i)

            delegates = []
            events = []

            self.rewrite_methods(i.methods, delegates, events, True)

            i.delegates = delegates
            i.events = events
            i.has_events = len(events) > 0

            subdir = self.__get_file_output_directory(i)

            if surrounding_types != None:
                for st in surrounding_types:
                    subdir = f"{subdir}/{st}"

            i.surrounding_types = surrounding_types

            Path(self.__OUTPUT_DIRECTORY + subdir).mkdir(parents=True, exist_ok=True)

            with open(f"{self.__OUTPUT_DIRECTORY}{subdir}/{i.name}.cs", "w") as f:
                print(
                    chevron.render(
                        interface_template, {"data": i, "extra_data": config}, self.__PARTIALS_DIRECTORY, warn=True
                    ),
                    file=f,
                )

    def render_classes(self, class_template) -> None:
        for c in self.classes.values():
            surrounding_types = None

            if c.is_nested_type:
                surrounding_types = c.namespace[c.namespace.find("::") + 2 :].split("::")
                c.namespace = c.namespace[: c.namespace.find("::")]

            self.__translate_comments(c.doc_comments)
            self.__translate_namespace(c)

            if c.base != None:
                self.__translate_namespace(c.base)

            delegates = []
            events = []

            for f in c.fields:
                self.__translate_type(f.type)

                if f.type.is_template:
                    assert f.type.template_arguments is not None

                    for ta in f.type.template_arguments:
                        self.__translate_type(ta.type)

            self.rewrite_methods(c.methods, delegates, events)

            c.delegates = delegates
            c.events = events
            c.has_events = len(events) > 0

            subdir = self.__get_file_output_directory(c)

            if surrounding_types != None:
                for st in surrounding_types:
                    subdir = f"{subdir}/{st}"

            c.surrounding_types = surrounding_types

            Path(self.__OUTPUT_DIRECTORY + subdir).mkdir(parents=True, exist_ok=True)

            with open(f"{self.__OUTPUT_DIRECTORY}{subdir}/{c.name}.cs", "w") as f:
                print(
                    chevron.render(
                        class_template, {"data": c, "extra_data": config}, self.__PARTIALS_DIRECTORY, warn=True
                    ),
                    file=f,
                )

    def rewrite_methods(self, methods, delegates, events, is_interface=False):
        for m in methods:
            self.__translate_comments(m.doc_comments)

            if m.return_type != None:
                self.__translate_type(m.return_type)

                if m.return_type.is_template:
                    assert m.return_type.template_arguments is not None

                    for ta in m.return_type.template_arguments:
                        self.__translate_type(ta.type)

            m.is_task = m.is_async_result or m.is_async_result_with_progress

            self.rewrite_task_doc_comments(m)

            if m.parameters is not None:
                for p in m.parameters:
                    self.__translate_type(p.type)

                    if p.type.is_template:
                        assert p.type.template_arguments is not None

                        for ta in p.type.template_arguments:
                            self.__translate_type(ta.type)

                    is_regular_method = not (m.is_async_result or m.is_async_result_with_progress or m.is_event)
                    if is_interface and is_regular_method:
                        continue

                    if not p.type.is_function_signature:
                        continue

                    assert p.type.function_signature is not None

                    m.results = p.type.function_signature.parameters
                    m.has_results = (p.type.function_signature.parameters is not None) and (len(p.type.function_signature.parameters) > 0)
                    m.has_multiple_results = len(m.results) > 1

                    param_name = p.name[0].upper() + p.name[1:]

                    if p.type.function_signature.parameters is not None:
                        for dp in p.type.function_signature.parameters:
                            self.__translate_type(dp.type)

                            full_type_name = f"{dp.type.namespace}::{dp.type.name}"
                            dp.type.is_result_base = full_type_name in self.classes and self.__class_derives_from(
                                        self.classes[full_type_name], "csp::systems", "ResultBase", self.classes
                                    )

                    delegate = {
                            "name": f"{m.name}{param_name}Delegate",
                            "method_name": m.name,
                            "return_type": p.type.function_signature.return_type,
                            "parameters": deepcopy(p.type.function_signature.parameters),
                            "has_parameters": (p.type.function_signature.parameters is not None)
                            and (len(p.type.function_signature.parameters) > 0),
                            "has_progress": m.is_async_result_with_progress,
                            "include_managed": is_regular_method,
                        }

                    delegates.append(delegate)
                    m.delegate = delegate
                    p.delegate = delegate

                    if not is_interface and is_regular_method:
                        continue

                    if m.is_event:
                        event_name = ""

                        assert m.name is not None

                        if m.name.startswith("Set") and m.name.endswith("Callback"):
                            event_name = f"On{m.name[len('Set'):-len('Callback')]}"
                        else:
                            warning_in_file(
                                    m.header_file,
                                    m.start_line,
                                    "Event functions should follow the naming pattern 'SetXCallback'.",
                                )
                            event_name = m.name

                        event = {
                                "name": event_name,
                                "class_name": m.parent_class.name,
                                "method_name": m.name,
                                "unique_method_name": m.unique_name,
                                "parameters": deepcopy(p.type.function_signature.parameters),
                                "has_parameters": (p.type.function_signature.parameters is not None)
                                and (len(p.type.function_signature.parameters) > 0),
                                "has_multiple_parameters": (p.type.function_signature.parameters is not None)
                                and (len(p.type.function_signature.parameters) > 1),
                                "delegate": delegate,
                            }

                        events.append(event)
                        m.event = event

                    m.parameters.remove(p)

                    if len(m.parameters) > 0:
                        m.parameters[-1].is_last = True

    def rewrite_task_doc_comments(self, m):
        if m.is_task and m.doc_comments != None and len(m.doc_comments) > 0:
            assert m.parameters is not None

            param = m.parameters[-1]
            m.doc_comments = m.doc_comments[:-1]

            assert param.type.function_signature is not None

            if len(param.type.function_signature.doc_comments) > 0:
                comment = param.type.function_signature.doc_comments[-1]
                comment = comment.replace("<", "&lt;").replace(">", "&gt;")

                comment_index = comment.find(" ")
                tag = comment[:comment_index]

                if tag != "@param":
                    error_in_file(m.header_file or "", -1, "Error in comment: " + comment)
                    error_in_file(m.header_file or "", -1, "Last doc comment must describe callback parameter")

                content = comment[comment_index + 1 :]
                comment_index = content.find(" ")
                        # var_name = content[:comment_index]
                content = content[comment_index + 1 :].lstrip()

                comment_index = content.find(":")

                while content[comment_index + 1] == ":":
                    comment_index = content.find(":", comment_index + 2)

                        # var_type = content[:comment_index]
                content = content[comment_index + 1 :].lstrip()

                if content[0].islower():
                    content = content.capitalize()

                m.doc_comments.append(f"<returns>{content}</returns>")
            else:
                m.doc_comments.append("<returns>The result for the request</returns>")

    def render_templates(self, templateclass_template) -> None:
        for t in self.templates.values():
            self.__translate_namespace(t.definition)

            for m in t.definition.methods:
                if m.return_type != None:
                    self.__translate_type(m.return_type)

                if m.parameters is not None:
                    for p in m.parameters:
                        self.__translate_type(p.type)

            subdir = self.__get_file_output_directory(t)
            Path(self.__OUTPUT_DIRECTORY + subdir).mkdir(parents=True, exist_ok=True)

            with open(f"{self.__OUTPUT_DIRECTORY}{subdir}/{t.definition.name}.cs", "w") as f:
                print(
                    chevron.render(
                        templateclass_template, {"data": t, "extra_data": config}, self.__PARTIALS_DIRECTORY, warn=True
                    ),
                    file=f,
                )
