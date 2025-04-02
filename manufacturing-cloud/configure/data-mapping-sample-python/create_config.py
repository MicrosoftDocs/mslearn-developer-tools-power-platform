import json
import os
import pathlib
from collections import OrderedDict
import pandas as pd


def make_to_from_object(cols, to_values, enums):
    """This function creates main to_from object for configuration.

    Args:
        cols (list): columns in excel file
        to_values (dictionary): values to map in ISA-95
        enums (dictionary): enum values if existing
    Returns:
        dictionary: to_from object
    """
    to_from_object = {}
    for i in range(2, len(cols)):
        from_value = cols[i]
        # a comment cell will not have corresponding to_value, so we should check for i in to_values
        if from_value and i in to_values:
            to_value = to_values[i]
            if to_value and from_value:
                from_value_lines = from_value.split("\n")

                first_from_value = from_value_lines[0]
                first_from_value = surround_unquoted_strings_with_curly_brackets(
                    first_from_value
                )
                to_from_object[to_value] = first_from_value

                if len(from_value_lines) > 1:
                    if from_value_lines[1] == "ENUMS":
                        enums[first_from_value] = {}
                        for i in range(2, len(from_value_lines)):
                            enum_line = from_value_lines[i]
                            enum_from_to = enum_line.split(">")
                            enum_from = enum_from_to[0].strip()
                            enum_to = enum_from_to[1].strip()
                            enums[first_from_value][enum_from] = enum_to           
    return to_from_object


def surround_unquoted_strings_with_curly_brackets(s: str) -> str:
    """Surrounds unquoted strings with curly brackets.

    Args:
        s (str): string to be wanted to surrounds with brackets

    Returns:
        str: amended string
    """
    new_string = ""
    substrings = s.split('"')
    for i in range(len(substrings)):
        s2 = substrings[i]
        if s2:
            if i % 2 == 0:
                new_string += "{" + substrings[i] + "}"
            else:
                new_string += substrings[i]
    return new_string


def add_prior_entity_to_dict(entity_name, mapping_dict, mapping_list, config_dictionary, enums):
    """Adds entity that is created to the mapping dictionary.

    Args:
        entity_name (string): name of the entity
        mapping_dict (dictionary): dictionary that holds all the mapping information
        mapping_list (list): list of the current mapping for the given entity
        config_dictionary (dictionary): dictionary that holds all the configuration information
        enum: the dictionary of from/to mapping values applied to a particular cell value
    """
    # wrap up the prior entity data
    if entity_name is not None:
        for file_path, to_from_lists in mapping_dict.items():
            for to_from_list in to_from_lists:
                file_name = os.path.basename(file_path)
                mapping = {
                    "input_file_names": file_name,
                    "to_from_fields": to_from_list
                }
                if enums:
                    mapping["enums"] = enums
                for subfield in to_from_lists:
                    if mapping not in mapping_list:
                        mapping_list.append(mapping)
        config_dictionary["entity_list"].append(
            {"entity_name": entity_name, "mapping_list": mapping_list})


def append_suffix(file_path):
    """Adds .csv to given path.

    Args:
        file_path (string): file path that needs .csv suffix

    Returns:
        string: full path with .csv suffix
    """
    if pathlib.Path(file_path).suffix == "":
        return file_path + ".csv"

    return file_path

def write_config_json(data, output_file):
    """Creates json configuration file.

    Args:
        data (dictionary): data to be written
        output_file (string): path of the outfput file
    """
    json_object = json.dumps(data, indent=4)
    try:
        with open(output_file, "w") as outfile:
            outfile.write(json_object)
        print("Configuration file is created.")
    except Exception:
        print(f"Can't write the file {output_file}")
        return


def create_entity_mappings_config(excel_mapping_file, config_dictionary=None):
    """Function that reads the excel and creates the configuration dictionary for entities.

    Args:
        excel_mapping_file (string): excel mapping file path to be read
        config_dictionary (dictionary, optional): configuration dictionary that needs to be filled

    Returns:
        dictionary: configuration dictionary that has the all data from the given excel
    """
    dataframe = pd.read_excel(
        excel_mapping_file, sheet_name="EntityMapping", header=None)
    # replace NAN values with empty string
    dataframe = dataframe.fillna("")
    entity_name = None
    to_values = {}
    mapping_dict = OrderedDict()
    enums = {}
    mapping_list = []

    if config_dictionary is None:
        config_dictionary = {
            "entity_list": [],
            "relationship_list": []
        }

    for index, row in dataframe.iterrows():
        cols = row.to_list()
        # looking for next entity name
        if cols[1] == "Entity":
            add_prior_entity_to_dict(
                entity_name, mapping_dict, mapping_list, config_dictionary, enums)

            # cleanup
            entity_name = cols[2]
            to_values = {}
            mapping_dict = OrderedDict()
            enums = {}
            mapping_list = []
        elif cols[2] == "id" and cols[0] == "":
            for i in range(2, len(cols)):
                to_value = cols[i]
                if to_value:
                    to_values[i] = to_value
        # looking for entity 'from values'
        elif entity_name is not None and cols[0] != '':
            file_path = append_suffix(cols[0])
            # expecting lines containing file name and 'from values'
            if file_path:
                to_from_object = make_to_from_object(cols, to_values, enums)
                if not mapping_dict.get(file_path):
                    # create 'to from' list per file name
                    mapping_dict[file_path] = []
                mapping_dict[file_path].append(to_from_object)

    add_prior_entity_to_dict(entity_name, mapping_dict,
                             mapping_list, config_dictionary, enums)
    return config_dictionary


def create_relationship_mappings_config(excel_mapping_file, config_dictionary):
    """Function that reads the excel and creates the configuration dictionary for relationships.

    Args:
        excel_mapping_file (string): excel mapping file path to be read
        config_dictionary (dictionary): configuration dictionary that needs to be filled

    Returns:
        dictionary: configuration dictionary that has the all data from the given excel
    """
    dataframe = pd.read_excel(
        excel_mapping_file, sheet_name="RelationshipMapping", header=0)
    # replace NAN values with empty string
    dataframe = dataframe.fillna("")

    for index, row in dataframe.iterrows():
        cols = row.to_list()
        source_entity_name = cols[0].strip()
        if source_entity_name == '':
            continue
        target_entity_name = cols[1].strip()
        source_join_column = cols[2].strip()
        target_join_column = cols[3].strip()
        source_join_column_filter = cols[4].strip()
        target_join_column_filter = cols[5].strip()
        source_file_name = append_suffix(cols[6].strip())
        target_file_name = append_suffix(cols[7].strip())

        config_dictionary["relationship_list"].append(
            {
                "source_entity_name": source_entity_name,
                "target_entity_name": target_entity_name,
                "source_join_column": source_join_column,
                "target_join_column": target_join_column,
                "source_join_column_filter": source_join_column_filter,
                "target_join_column_filter": target_join_column_filter,
                "source_file_name": source_file_name,
                "target_file_name": target_file_name
            }
        )
    return config_dictionary
