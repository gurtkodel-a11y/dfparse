"""
Programmatic protobuf message definitions for the DFHack remote protocol.
Builds message classes using google.protobuf's descriptor API without needing protoc.
"""

from enum import IntEnum

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

_pool = descriptor_pool.Default()
_LABEL_REQUIRED = descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED
_LABEL_OPTIONAL = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_LABEL_REPEATED = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
_TYPE_STRING    = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_TYPE_INT32     = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
_TYPE_UINT32    = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_TYPE_SINT32    = descriptor_pb2.FieldDescriptorProto.TYPE_SINT32
_TYPE_FIXED32   = descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32
_TYPE_BOOL      = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
_TYPE_ENUM      = descriptor_pb2.FieldDescriptorProto.TYPE_ENUM
_TYPE_MESSAGE   = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE


def _field(msg, name, number, ftype, label=_LABEL_OPTIONAL, type_name=None, default=None):
    f = msg.field.add()
    f.name = name
    f.number = number
    f.type = ftype
    f.label = label
    if type_name:
        f.type_name = type_name
    if default is not None:
        f.default_value = str(default)
    return f


def _build_basic():
    """Basic.proto — shared data types used across the API."""
    fp = descriptor_pb2.FileDescriptorProto()
    fp.name = "dfhack/Basic.proto"
    fp.package = "dfproto"
    fp.syntax = "proto2"

    # NameInfo
    m = fp.message_type.add()
    m.name = "NameInfo"
    _field(m, "first_name",   1, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "nickname",     2, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "language_id",  3, _TYPE_INT32,  _LABEL_OPTIONAL, default="-1")
    _field(m, "last_name",    4, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "english_name", 5, _TYPE_STRING, _LABEL_OPTIONAL)

    # NameTriple (used inside UnitCurseInfo)
    m = fp.message_type.add()
    m.name = "NameTriple"
    _field(m, "normal",    1, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "plural",    2, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "adjective", 3, _TYPE_STRING, _LABEL_OPTIONAL)

    # SkillInfo
    m = fp.message_type.add()
    m.name = "SkillInfo"
    _field(m, "id",         1, _TYPE_INT32, _LABEL_REQUIRED)
    _field(m, "level",      2, _TYPE_INT32, _LABEL_REQUIRED)
    _field(m, "experience", 3, _TYPE_INT32, _LABEL_REQUIRED)

    # UnitMiscTrait
    m = fp.message_type.add()
    m.name = "UnitMiscTrait"
    _field(m, "id",    1, _TYPE_INT32, _LABEL_REQUIRED)
    _field(m, "value", 2, _TYPE_INT32, _LABEL_REQUIRED)

    # UnitCurseInfo
    m = fp.message_type.add()
    m.name = "UnitCurseInfo"
    _field(m, "add_tags1", 1, _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "rem_tags1", 2, _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "add_tags2", 3, _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "rem_tags2", 4, _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "name",      5, _TYPE_MESSAGE, _LABEL_OPTIONAL, type_name=".dfproto.NameTriple")

    # BasicUnitInfo — field numbers match Basic.proto exactly
    m = fp.message_type.add()
    m.name = "BasicUnitInfo"
    _field(m, "unit_id",           1,  _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "name",              2,  _TYPE_MESSAGE, _LABEL_OPTIONAL,  type_name=".dfproto.NameInfo")
    _field(m, "flags1",            3,  _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "flags2",            4,  _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "flags3",            5,  _TYPE_FIXED32, _LABEL_REQUIRED)
    _field(m, "race",              6,  _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "caste",             7,  _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "gender",            8,  _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "civ_id",            9,  _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "histfig_id",        10, _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "labors",            11, _TYPE_INT32,   _LABEL_REPEATED)
    _field(m, "skills",            12, _TYPE_MESSAGE, _LABEL_REPEATED,  type_name=".dfproto.SkillInfo")
    _field(m, "pos_x",             13, _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "pos_y",             14, _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "pos_z",             15, _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "curse",             16, _TYPE_MESSAGE, _LABEL_OPTIONAL,  type_name=".dfproto.UnitCurseInfo")
    _field(m, "death_id",          17, _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "death_flags",       18, _TYPE_UINT32,  _LABEL_OPTIONAL)
    _field(m, "squad_id",          19, _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "squad_position",    20, _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "burrows",           21, _TYPE_INT32,   _LABEL_REPEATED)
    _field(m, "profession",        22, _TYPE_INT32,   _LABEL_OPTIONAL,  default="-1")
    _field(m, "custom_profession", 23, _TYPE_STRING,  _LABEL_OPTIONAL)
    _field(m, "misc_traits",       24, _TYPE_MESSAGE, _LABEL_REPEATED,  type_name=".dfproto.UnitMiscTrait")

    # BasicUnitInfoMask
    m = fp.message_type.add()
    m.name = "BasicUnitInfoMask"
    _field(m, "labors",      1, _TYPE_BOOL, _LABEL_OPTIONAL, default="false")
    _field(m, "skills",      2, _TYPE_BOOL, _LABEL_OPTIONAL, default="false")
    _field(m, "profession",  3, _TYPE_BOOL, _LABEL_OPTIONAL, default="false")
    _field(m, "misc_traits", 4, _TYPE_BOOL, _LABEL_OPTIONAL, default="false")

    # BasicSquadInfo
    m = fp.message_type.add()
    m.name = "BasicSquadInfo"
    _field(m, "squad_id", 1, _TYPE_INT32,   _LABEL_REQUIRED)
    _field(m, "name",     2, _TYPE_MESSAGE, _LABEL_OPTIONAL, type_name=".dfproto.NameInfo")
    _field(m, "alias",    3, _TYPE_STRING,  _LABEL_OPTIONAL)
    _field(m, "members",  4, _TYPE_SINT32,  _LABEL_REPEATED)

    # UnitLaborState
    m = fp.message_type.add()
    m.name = "UnitLaborState"
    _field(m, "unit_id", 1, _TYPE_INT32, _LABEL_REQUIRED)
    _field(m, "labor",   2, _TYPE_INT32, _LABEL_REQUIRED)
    _field(m, "value",   3, _TYPE_BOOL,  _LABEL_REQUIRED)

    _pool.Add(fp)


def _build_core_protocol():
    fp = descriptor_pb2.FileDescriptorProto()
    fp.name = "dfhack/CoreProtocol.proto"
    fp.package = "dfproto"
    fp.syntax = "proto2"

    # EmptyMessage
    fp.message_type.add().name = "EmptyMessage"

    # IntMessage
    m = fp.message_type.add()
    m.name = "IntMessage"
    _field(m, "value", 1, _TYPE_INT32, _LABEL_REQUIRED)

    # StringMessage
    m = fp.message_type.add()
    m.name = "StringMessage"
    _field(m, "value", 1, _TYPE_STRING, _LABEL_REQUIRED)

    # StringListMessage
    m = fp.message_type.add()
    m.name = "StringListMessage"
    _field(m, "value", 1, _TYPE_STRING, _LABEL_REPEATED)

    # CoreTextFragment (with nested color enum)
    m = fp.message_type.add()
    m.name = "CoreTextFragment"
    e = m.enum_type.add()
    e.name = "color"
    for i, name in enumerate(["BLACK","BLUE","GREEN","CYAN","RED","MAGENTA","BROWN",
                               "LGRAY","DGRAY","LBLUE","LGREEN","LCYAN","LRED","LMAGENTA","YELLOW","WHITE"]):
        ev = e.value.add(); ev.name = name; ev.number = i
    _field(m, "text",  1, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "color", 2, _TYPE_ENUM,   _LABEL_OPTIONAL,
           type_name=".dfproto.CoreTextFragment.color", default="LGRAY")

    # CoreTextNotification
    m = fp.message_type.add()
    m.name = "CoreTextNotification"
    _field(m, "fragments", 1, _TYPE_MESSAGE, _LABEL_REPEATED,
           type_name=".dfproto.CoreTextFragment")

    # CoreErrorNotification
    m = fp.message_type.add()
    m.name = "CoreErrorNotification"
    e = m.enum_type.add()
    e.name = "T_code"
    for i, name in enumerate(["LINK_FAILURE","NEEDS_CONSOLE","WRONG_USAGE","NOT_IMPLEMENTED",
                               "NO_SESSION","INVALID_ARGUMENT","ACCESS_DENIED","INVALID_PARENT",
                               "DUPLICATE","LOGIC_ERROR","INTERNAL_ERROR"], start=1):
        ev = e.value.add(); ev.name = name; ev.number = i
    _field(m, "code", 1, _TYPE_ENUM, _LABEL_REQUIRED, type_name=".dfproto.CoreErrorNotification.T_code")

    # CoreBindRequest
    m = fp.message_type.add()
    m.name = "CoreBindRequest"
    _field(m, "method",     1, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "input_msg",  2, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "output_msg", 3, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "plugin",     4, _TYPE_STRING, _LABEL_OPTIONAL)

    # CoreBindReply
    m = fp.message_type.add()
    m.name = "CoreBindReply"
    _field(m, "assigned_id", 1, _TYPE_INT32, _LABEL_REQUIRED)

    # CoreRunCommandRequest
    m = fp.message_type.add()
    m.name = "CoreRunCommandRequest"
    _field(m, "command",   1, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "arguments", 2, _TYPE_STRING, _LABEL_REPEATED)

    # CoreRunLuaRequest
    m = fp.message_type.add()
    m.name = "CoreRunLuaRequest"
    _field(m, "module",   1, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "function", 2, _TYPE_STRING, _LABEL_REQUIRED)
    _field(m, "args",     3, _TYPE_STRING, _LABEL_REPEATED)

    _pool.Add(fp)


def _build_basic_api():
    fp = descriptor_pb2.FileDescriptorProto()
    fp.name = "dfhack/BasicApi.proto"
    fp.package = "dfproto"
    fp.syntax = "proto2"
    fp.dependency.append("dfhack/Basic.proto")

    # GetWorldInfoOut
    m = fp.message_type.add()
    m.name = "GetWorldInfoOut"
    e = m.enum_type.add()
    e.name = "Mode"
    for num, name in [(1, "DWARF"), (2, "ADVENTURE"), (3, "LEGENDS")]:
        ev = e.value.add(); ev.name = name; ev.number = num
    _field(m, "mode",       1, _TYPE_ENUM,   _LABEL_OPTIONAL, type_name=".dfproto.GetWorldInfoOut.Mode")
    _field(m, "save_dir",   2, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "world_name", 3, _TYPE_STRING, _LABEL_OPTIONAL)
    _field(m, "civ_id",     4, _TYPE_INT32,  _LABEL_OPTIONAL)
    _field(m, "site_id",    5, _TYPE_INT32,  _LABEL_OPTIONAL)
    _field(m, "group_id",   6, _TYPE_INT32,  _LABEL_OPTIONAL)
    _field(m, "race_id",    7, _TYPE_INT32,  _LABEL_OPTIONAL)

    # ListUnitsIn
    m = fp.message_type.add()
    m.name = "ListUnitsIn"
    _field(m, "mask",     1, _TYPE_MESSAGE, _LABEL_OPTIONAL, type_name=".dfproto.BasicUnitInfoMask")
    _field(m, "id_list",  2, _TYPE_INT32,   _LABEL_REPEATED)
    _field(m, "race",     3, _TYPE_INT32,   _LABEL_OPTIONAL)
    _field(m, "civ_id",   4, _TYPE_INT32,   _LABEL_OPTIONAL)
    _field(m, "scan_all", 5, _TYPE_BOOL,    _LABEL_OPTIONAL)
    _field(m, "dead",     6, _TYPE_BOOL,    _LABEL_OPTIONAL)
    _field(m, "alive",    7, _TYPE_BOOL,    _LABEL_OPTIONAL)
    _field(m, "sane",     8, _TYPE_BOOL,    _LABEL_OPTIONAL)

    # ListUnitsOut
    m = fp.message_type.add()
    m.name = "ListUnitsOut"
    _field(m, "value", 1, _TYPE_MESSAGE, _LABEL_REPEATED, type_name=".dfproto.BasicUnitInfo")

    # ListSquadsIn (empty message)
    fp.message_type.add().name = "ListSquadsIn"

    # ListSquadsOut
    m = fp.message_type.add()
    m.name = "ListSquadsOut"
    _field(m, "value", 1, _TYPE_MESSAGE, _LABEL_REPEATED, type_name=".dfproto.BasicSquadInfo")

    _pool.Add(fp)


def _build_rfr_dig():
    """RemoteFortressReader dig designation messages (SendDigCommand RPC).

    Must use package "RemoteFortressReader" so the bind request sends the correct
    full type names (e.g. RemoteFortressReader.DigCommand) that the server registered.
    """
    fp = descriptor_pb2.FileDescriptorProto()
    fp.name = "dfhack/RFRDig.proto"
    fp.package = "RemoteFortressReader"
    fp.syntax = "proto2"

    e = fp.enum_type.add()
    e.name = "TileDigDesignation"
    for num, name in [
        (0, "NO_DIG"),
        (1, "DEFAULT_DIG"),
        (2, "UP_DOWN_STAIR_DIG"),
        (3, "CHANNEL_DIG"),
        (4, "RAMP_DIG"),
        (5, "DOWN_STAIR_DIG"),
        (6, "UP_STAIR_DIG"),
    ]:
        ev = e.value.add(); ev.name = name; ev.number = num

    m = fp.message_type.add()
    m.name = "Coord"
    _field(m, "x", 1, _TYPE_INT32, _LABEL_OPTIONAL)
    _field(m, "y", 2, _TYPE_INT32, _LABEL_OPTIONAL)
    _field(m, "z", 3, _TYPE_INT32, _LABEL_OPTIONAL)

    m = fp.message_type.add()
    m.name = "DigCommand"
    _field(m, "designation", 1, _TYPE_ENUM,    _LABEL_OPTIONAL, type_name=".RemoteFortressReader.TileDigDesignation")
    _field(m, "locations",   2, _TYPE_MESSAGE, _LABEL_REPEATED, type_name=".RemoteFortressReader.Coord")

    _pool.Add(fp)


_build_basic()           # must precede basic_api (dependency)
_build_core_protocol()
_build_basic_api()
_build_rfr_dig()


def _cls(full_name):
    return message_factory.GetMessageClass(_pool.FindMessageTypeByName(full_name))


# Core protocol messages
EmptyMessage          = _cls("dfproto.EmptyMessage")
IntMessage            = _cls("dfproto.IntMessage")
StringMessage         = _cls("dfproto.StringMessage")
StringListMessage     = _cls("dfproto.StringListMessage")
CoreTextFragment      = _cls("dfproto.CoreTextFragment")
CoreTextNotification  = _cls("dfproto.CoreTextNotification")
CoreErrorNotification = _cls("dfproto.CoreErrorNotification")
CoreBindRequest       = _cls("dfproto.CoreBindRequest")
CoreBindReply         = _cls("dfproto.CoreBindReply")
CoreRunCommandRequest = _cls("dfproto.CoreRunCommandRequest")
CoreRunLuaRequest     = _cls("dfproto.CoreRunLuaRequest")

# Basic.proto shared types
NameInfo          = _cls("dfproto.NameInfo")
SkillInfo         = _cls("dfproto.SkillInfo")
BasicUnitInfo     = _cls("dfproto.BasicUnitInfo")
BasicUnitInfoMask = _cls("dfproto.BasicUnitInfoMask")
BasicSquadInfo    = _cls("dfproto.BasicSquadInfo")
UnitLaborState    = _cls("dfproto.UnitLaborState")

# Basic API messages
GetWorldInfoOut = _cls("dfproto.GetWorldInfoOut")
ListUnitsIn     = _cls("dfproto.ListUnitsIn")
ListUnitsOut    = _cls("dfproto.ListUnitsOut")
ListSquadsIn    = _cls("dfproto.ListSquadsIn")
ListSquadsOut   = _cls("dfproto.ListSquadsOut")

# RemoteFortressReader dig messages
Coord      = _cls("RemoteFortressReader.Coord")
DigCommand = _cls("RemoteFortressReader.DigCommand")


class TileDigDesignation(IntEnum):
    NO_DIG        = 0
    DEFAULT_DIG   = 1  # dig walls, fell trees, gather plants, remove ramps
    UP_DOWN_STAIR = 2
    CHANNEL       = 3
    RAMP          = 4
    DOWN_STAIR    = 5
    UP_STAIR      = 6
