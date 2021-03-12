from enum import Enum, auto
from typing import Union, Tuple, Optional, Any, Iterable
from abc import ABC
from dataclasses import dataclass
import re
from sigma.exceptions import SigmaValueError, SigmaRegularExpressionError

class SpecialChars(Enum):
    """Enumeration of supported special characters"""
    WILDCARD_MULTI = auto()
    WILDCARD_SINGLE = auto()

escape_char = "\\"
char_mapping = {
    "*": SpecialChars.WILDCARD_MULTI,
    "?": SpecialChars.WILDCARD_SINGLE,
}
special_char_mapping = {
    v: k
    for k, v in char_mapping.items()
}

class SigmaType(ABC):
    """Base class for Sigma value types"""
    pass

class SigmaNull(SigmaType):
    """Empty/none/null value"""
    def __init__(self, dummy : Optional[Any] = None):
        pass

    def __eq__(self, other : "SigmaNull") -> bool:
        return isinstance(other, self.__class__)

class SigmaString(SigmaType):
    """
    Strings in Sigma detection values containing wildcards.
    """
    s : Tuple[Union[str, SpecialChars]]      # the string is represented as sequence of strings and characters with special meaning

    def __init__(self, s : Optional[str] = None):
        """
        Initializes SigmaString instance from raw string by parsing it:

        * characters from char_mapping are interpreted as special characters and interrupt the plain string in the resulting sequence
        * escape_char disables special character mapping in the next character
        * if escaping character is followed by a character without special meaning the escaping character is used as plain character
        """
        if s is None:
            s = ""
        r = list()
        acc = ""            # string accumulation until special character appears
        escaped = False     # escape mode flag: characters in this mode are always accumulated
        for c in s:
            if escaped:                 # escaping mode?
                if c in char_mapping or c == escape_char:   # accumulate if character is special or escaping character
                    acc += c
                else:                   # accumulate escaping and current character (this allows to use plain backslashes in values)
                    acc += escape_char + c
                escaped = False
            elif c == escape_char:      # escaping character? enable escaped mode for next character
                escaped = True
            else:                       # "normal" string parsing
                if c in char_mapping:   # character is special character?
                    if acc != "":
                        r.append(acc)  # append accumulated string to parsed result if there was something
                    r.append(char_mapping[c])      # append special character to parsed result
                    acc = ""            # accumulation reset
                else:                   # characters without special meaning aren't accumulated
                    acc += c
        if escaped:                     # String ended in escaping mode: accumulate escaping character
            acc += escape_char
        if acc != "":                   # append accumulated remainder
            r.append(acc)
        self.s = tuple(r)
        self.protected = True

    def __add__(self, other: Union["SigmaString", str, SpecialChars]) -> "SigmaString":
        s = self.__class__()
        if isinstance(other, self.__class__):
            s.s = self.s + other.s
        elif isinstance(other, (str, SpecialChars)):
            s.s = self.s + (other,)
        else:
            return NotImplemented
        return s

    def __radd__(self, other: Union[str, SpecialChars]) -> "SigmaString":
        if isinstance(other, (str, SpecialChars)):
            s = self.__class__()
            s.s = (other,) + self.s
            return s
        else:
            return NotImplemented

    def __eq__(self, other : Union["SigmaString", str]) -> bool:
        if isinstance(other, str):
            return self == self.__class__(other)
        elif isinstance(other, self.__class__):
            return self.s == other.s
        else:
            raise NotImplementedError("SigmaString can only be compared with a string or another SigmaString")

    def __str__(self) -> str:
        return "".join(
            s if isinstance(s, str)
            else special_char_mapping[s]
            for s in self.s
        )

    def __bytes__(self) -> bytes:
        return str(self).encode()

    def __len__(self) -> int:
        return len(str(self))

    def startswith(self, val : Union[str, SpecialChars]) -> bool:
        """Check if string starts with a given string or special character."""
        c = self.s[0]
        if not isinstance(val, type(c)):    # can't match if types differ
            return False
        elif isinstance(c, str):            # pass startswith invocation to string objects
            return c.startswith(val)
        else:                               # direct comparison of SpecialChars
            return c == val

    def endswith(self, val : Union[str, SpecialChars]) -> bool:
        """Check if string ends with a given string or special character."""
        c = self.s[-1]
        if not isinstance(val, type(c)):    # can't match if types differ
            return False
        elif isinstance(c, str):            # pass endswith invocation to string objects
            return c.endswith(val)
        else:                               # direct comparison of SpecialChars
            return c == val

    def contains_special(self) -> bool:
        """Check if string contains special characters."""
        return any([
            isinstance(item, SpecialChars)
            for item in self.s
        ])

    def __iter__(self) -> Iterable[Union[str, SpecialChars]]:
        for item in self.s:
            if isinstance(item, str):       # yield single characters of string parts
                for char in item:
                    yield char
            else:
                yield item

    def convert(
            self,
            escape_char : Optional[str] = "\\",
            wildcard_multi : Optional[str] = "*",
            wildcard_single : Optional[str] = "?",
            add_escaped : str = "",
            filter_chars : str = "",
        ) -> str:
        """
        Convert SigmaString into a query string or pattern. The following parameters allow to change the behavior:

        * escape_char: the character used to escape special characters. By default these are only the wildcard characters.
        * wildcard_multi and wildcard_single: strings that should be output as wildcards for multiple and single characters.
        * add_escaped: characters which are escaped in addition to the wildcards
        * filter_chars: characters that are filtered out.

        Setting one of the wildcard or multiple parameters to None indicates that this feature is not supported. Appearance
        of these characters in a string will raise a SigmaValueError.
        """
        s = ""
        escaped_chars = frozenset((wildcard_multi or "") + (wildcard_single or "") + add_escaped)

        for c in self:
            if isinstance(c, str):      # c is plain character
                if c in filter_chars:   # Skip filtered characters
                    continue
                if c in escaped_chars:
                    s += escape_char
                s += c
            else:                       # special handling for special characters
                if c == SpecialChars.WILDCARD_MULTI:
                    if wildcard_multi is not None:
                        s += wildcard_multi
                    else:
                        raise SigmaValueError("Multi-character wildcard not specified for conversion")
                elif c == SpecialChars.WILDCARD_SINGLE:
                    if wildcard_single is not None:
                        s += wildcard_single
                    else:
                        raise SigmaValueError("Single-character wildcard not specified for conversion")
        return s

@dataclass
class SigmaNumber(SigmaType):
    """Numeric value type"""
    number : Union[int, float]

    def __post_init__(self):
        try:
            self.number = int(self.number)
        except ValueError as e:
            raise SigmaValueError("Invalid number") from e

    def __str__(self):
        return str(self.number)

    def __eq__(self, other : Union["SigmaNumber", int]) -> bool:
        if isinstance(other, int):
            return self.number == other
        else:
            return self.number == other.number

@dataclass
class SigmaRegularExpression(SigmaType):
    regexp : str

    def __post_init__(self):
        """Verify if regular expression is valid by compiling it"""
        try:
            re.compile(self.regexp)
        except re.error as e:
            raise SigmaRegularExpressionError("Invalid regular expression") from e

    def escape(self, escaped : Tuple[str] = (), escape_char : str = "\\") -> str:
        """Escape strings from escaped tuple as well as escape_char itself with escape_char."""
        r = "|".join([ re.escape(e) for e in [*escaped, escape_char]])      # Generate regulear expressions from sequences that should be escaped and the escape char itself
        pos = [     # determine positions of matches in regular expression
            m.start()
            for m in re.finditer(r, self.regexp)
        ]
        ranges = zip([None, *pos], [*pos, None])    # string chunk ranges with escapes in between
        ranges = list(ranges)
        return escape_char.join([
            self.regexp[i:j]
            for i,j in ranges
        ])

type_map = {
    int         : SigmaNumber,
    float       : SigmaNumber,
    str         : SigmaString,
    type(None)  : SigmaNull,
}

def sigma_type(v : Optional[Union[int, float, str]]):
    """Return Sigma type from Python value"""
    for t, st in type_map.items():
        if isinstance(v, t):
            return st(v)
