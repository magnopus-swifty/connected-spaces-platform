import sys
import unittest
from word_reader import WordReader
import Parser
import MetadataTypes

class TestParser(unittest.TestCase):
    def setUp(self):
        self.parser = Parser.Parser(log_file=sys.stdout)

    def test_parse_empty_enum(self):
        """ Test parsing an empty enum. """
        wordreader = WordReader(
        """
        enum Foo {}
        """)
        wordreader.next_word()  # 'enum'

        result = self.parser._Parser__parse_enum("test.h", wordreader)

        self.assertEqual(result.namespace, "")
        self.assertEqual(result.name, "Foo")
        self.assertEqual(result.full_safe_type_name, "_Foo")
        self.assertEqual(result.fields, [])
        self.assertEqual(result.is_flags, False)
        self.assertEqual(result.is_nested_type, False)
        self.assertEqual(result.doc_comments, None)

    def test_parse_enum_fields(self):
        """ Test parsing an enum with fields. """
        wordreader = WordReader(
        """
        enum EnumName {
            Foo,
            Bar,
            Baz
        }
        """)
        wordreader.next_word()  # 'enum'
        
        result = self.parser._Parser__parse_enum("test.h", wordreader)

        self.assertEqual(result.namespace, "")
        self.assertEqual(result.name, "EnumName")
        self.assertEqual(result.full_safe_type_name, "_EnumName")
        self.assertEqual(result.fields, [
            MetadataTypes.EnumFieldMetadata("Foo", None, None),
            MetadataTypes.EnumFieldMetadata("Bar", None, None),
            MetadataTypes.EnumFieldMetadata("Baz", None, None)
        ])
        self.assertEqual(result.is_flags, False)
        self.assertEqual(result.is_nested_type, False)
        self.assertEqual(result.doc_comments, None)

    def test_parse_enum_field_values(self):
        """ Test parsing an enum with fields that have explicit values. """
        wordreader = WordReader(
        """
        enum EnumName {
            Foo = -1,
            Bar = 0,
            Baz = 1234
        }
        """)
        wordreader.next_word()  # 'enum'
        
        result = self.parser._Parser__parse_enum("test.h", wordreader)

        self.assertEqual(result.namespace, "")
        self.assertEqual(result.name, "EnumName")
        self.assertEqual(result.full_safe_type_name, "_EnumName")
        self.assertEqual(result.fields, [
            # Note that values are stored as strings
            MetadataTypes.EnumFieldMetadata("Foo", "-1", None),
            MetadataTypes.EnumFieldMetadata("Bar", "0", None),
            MetadataTypes.EnumFieldMetadata("Baz", "1234", None)
        ])
        self.assertEqual(result.is_flags, False)
        self.assertEqual(result.is_nested_type, False)
        self.assertEqual(result.doc_comments, None)


class TestParserParseFunction(unittest.TestCase):
    def setUp(self):
        self.parser = Parser.Parser(log_file=sys.stdout)
        self.maxDiff = None

    def __parse_function(self, function_str: str) -> MetadataTypes.FunctionMetadata:
        wordreader = WordReader(function_str)
        word = wordreader.next_word()  # Advance to first word
        func = self.parser._Parser__parse_function("test.h", wordreader, word)
        self.assertIsNone(wordreader.next_word())  # Ensure we consumed all words
        return func
    
    def __parse_type(self, type_str: str) -> MetadataTypes.TypeMetadata:
        wordreader = WordReader(type_str)
        word = wordreader.next_word()
        type, word = self.parser._Parser__parse_type(wordreader, word)
        self.assertIsNone(word)  # Ensure we consumed all words
        return type

    def test_missing_semicolon_wtf(self):
        """ Test that if you leave off the semicolon, parsing fails in an exciting fashion. """
        with self.assertRaisesRegex(Parser.ParserError, ".*(WTF).*"):
            self.__parse_function("void FunctionName()")

    def test_parse_function_no_params(self):
        """ Test parsing a function with no parameters. """
        result = self.__parse_function(
        """
        void FunctionName();
        """)

        self.assertEqual(result.namespace, "")
        self.assertEqual(result.name, "FunctionName")
        self.assertEqual(result.return_type, None)
        self.assertEqual(result.parameters, [])
        self.assertEqual(result.is_static, False)
        self.assertEqual(result.is_const, False)
        self.assertEqual(result.doc_comments, None)

    def test_parse_function_with_params(self):
        """ Test parsing a function with parameters. """
        result = self.__parse_function("int FunctionName(int param1);")

        int_type = self.__parse_type("int")

        arg1 = MetadataTypes.ParameterMetadata(
            name="param1",
            type=int_type,
            is_out=False,
            is_in_out=False,
            is_last=True)

        expected = MetadataTypes.FunctionMetadata(
            header_file="test.h",
            start_line=1,
            end_line=1,
            namespace="",
            name="FunctionName",
            return_type=int_type,
            has_return=True,
            has_parameters=True,
            parameters=[arg1])

        # We don't care about these fields for this test
        expected.header_file = result.header_file

        self.assertDictEqual(result.__dict__, expected.__dict__)

    def test_parse_function_with_multiple_params(self):
        """ Test parsing a function with multiple parameters. """
        result = self.__parse_function("float FunctionName(int param1, const char* param2, double param3);")

        int_type = self.__parse_type("int")
        const_char_ptr_type = self.__parse_type("const char*")
        double_type = self.__parse_type("double")

        arg1 = MetadataTypes.ParameterMetadata(
            name="param1",
            type=int_type,
            is_out=False,
            is_in_out=False,
            is_last=False)

        arg2 = MetadataTypes.ParameterMetadata(
            name="param2",
            type=const_char_ptr_type,
            is_out=False,
            is_in_out=False,
            is_last=False)

        arg3 = MetadataTypes.ParameterMetadata(
            name="param3",
            type=double_type,
            is_out=False,
            is_in_out=False,
            is_last=True)

        expected = MetadataTypes.FunctionMetadata(
            header_file="test.h",
            start_line=1,
            end_line=1,
            namespace="",
            name="FunctionName",
            return_type=self.__parse_type("float"),
            has_return=True,
            has_parameters=True,
            parameters=[arg1, arg2, arg3])

        # We don't care about these fields for this test
        expected.header_file = result.header_file

        self.assertDictEqual(result.__dict__, expected.__dict__)
