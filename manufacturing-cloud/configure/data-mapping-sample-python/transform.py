import csv
from datetime import datetime, timedelta
import re
import json
import os
from pathlib import Path
import sys
import ast
import pandas as pd

# variables
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
SOURCE_DATE_FORMATS = ['%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%m/%d/%Y %H:%M:%S', '%d-%m-%Y %H:%M'] # potential source datetime formats; to be extended upon further use case
# dictionary containing metadata for all entities
ENTITIES = {}
MAPPING_COLUMN_NAMES = ['Source type', 'Source PrimaryKey',
                        'Target Type', 'Target PrimaryKey', 'Relationship Type']

# functions for cleaning up the data and reading ISA-95 entities


def get_seconds_from_hhmmss(time_str):
    """Converts given date to seconds.

    Args:
        time_str (string): date in string format

    Returns:
        integer: converted seconds
    """
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def strip_enclosing_braces(text):
    """Strips enclosing braces.

    Args:
        text (string): text to be removed from braces

    Returns:
        string: text without enclosing braces
    """
    if text.startswith('{') and text.endswith('}'):
        return text[1:-1]
    return text


def get_brace_enclosed_text(text):
    """Finds substrings from the given text which are enclosed with braces.

    Args:
        text (string): text to be searched

    Returns:
        list: list of matched patterns
    """
    pattern = r'\{[^}]*\}'
    matches = re.findall(pattern, text)
    return matches


def get_date(date):
    """Converts string in to the date format.

    Args:
        date (string): date in a string format

    Returns:
        date: date
    """
    for SOURCE_DATE_FORMAT in SOURCE_DATE_FORMATS:
        try:
            return datetime.strptime(date, SOURCE_DATE_FORMAT)
        except Exception:
            continue
                
    return None
        

def round_time(dt):
    """Rounds time to nearest second.

    Args:
        dt (date): date object to be rounded

    Returns:
        date: rounded date
    """
    return (dt + timedelta(milliseconds=499)).replace(microsecond=0)


def format_date(date_string):
    """Formats date string.

    Args:
        date_string (string): date string to be formatted

    Returns:
        string: formatted date string
    """
    date_object = get_date(date_string)
    if date_object:
        date_object = round_time(date_object)
        date_string = date_object.strftime(DATE_FORMAT)
    return str(date_string)


def get_brace_enclosed_value(item, substring):
    """Gets value from the excel cell if a given string is inside braces.

    Args:
        item (dictionary): dictionary includes key and value inside braces
        substring (string): brace enclosed text

    Returns:
        string: value corresponds to brace enclosed text in the raw excell cell
    """
    stripped = strip_enclosing_braces(substring)
    if '.' in stripped:
        value = get_value(item, stripped)
    else:
        value = item[stripped]
    if value:
        value = format_date(value)
        return value
    else:
        return ""

def get_splitted_column_string(input_str):
    """Divides given input string in SPLIT(Column_name, Delimeter, index) into [column_name, delimeter, index] list.

    Args:
        input_str (string): input to be divided

    Returns:
        list: [column_name, delimeter, index]
    """
    substr = input_str[6:-1]
    column = substr.split(',')[0].strip()
    delimeter = substr.split(',')[1].strip().strip('\'')
    index = substr.split(',')[2].strip()
    return [column, delimeter, index]

def format_split(item, column_str):
    """If there is a SPLIT(column_name, delimeter, index) format, then gets the value accordingly.

    Args:
        item (dictionary): row to be read
        column_str (string): SPLIT(column_name, delimeter, index) formatted string

    Returns:
        string: extracted value
    """
    column_name, delimeter, index = get_splitted_column_string(column_str)
    value = get_value(item, column_name)
    value = value.split(delimeter)[int(index)]   
    return value

def is_split_required(input_str):
    """Checks if a given string has 'SPLIT' substring.

    Args:
        input_str (string): input string

    Returns:
        boolean: result of the check
    """
    return "SPLIT" in input_str


def get_entity(entity_name, entity_path):
    """Gets entities dtdl content.

    Args:
        entity_name (string): entity name
        entity_path (string): path of entity file

    Returns:
        jsob object: dtdl content
    """
    entity_path = entity_path + entity_name.replace(" ", "") + ".json"
    file = open(entity_path, 'r')
    json_content = file.read()
    file.close()
    return json_content


def cache_entity_metadata(entity_list, entity_path):
    """Caches all metadata for given entities in the configuration file from dtdls.

    Args:
        entity_list (list): list of entities
        entity_path (path): path of the dtdl files
    """
    for entity in entity_list:
        entity_name = entity.get('entity_name')
        response = get_entity(entity_name=entity_name, entity_path=entity_path)
        entity = json.loads(response)
        ENTITIES[entity_name] = entity


def generate_primary_key(extracted_row, entity_name):
    """Generates primary key.

    Args:
        extracted_row (dictionary): row that is currently mapped
        entity_name (string): entity name

    Returns:
        string: primary key of mapped row
    """
    entity_metadata = ENTITIES.get(entity_name)
    primary_key = ""
    for column in entity_metadata["columns"]:
        if column["primaryKey"] == 'true':
            primary_key += extracted_row[column["name"]]
    return primary_key.replace(" ", "")


def create_parent_folder(file_path):
    """Creates parent folder to a given file path.

    Args:
        file_path (string): file path
    """
    parent_directory = Path(file_path).parent
    parent_directory.mkdir(parents=True, exist_ok=True)


def get_value(item, substring):
    """If the string have '.', then it gets the value for the latest key.

    Args:
        item (dictionary): dictionary that has keys and value
        path (string): substring that has '.'

    Returns:
        dictionary: output 
    """
    try:
        keys = substring.split(".")
        current_dict = item
        for key in keys:
            current_dict = current_dict.setdefault(key, {})
        return current_dict
    except Exception:
        return None


def get_entity_name(entity_id):
    """Gets entity name from the given entity id.

    Args:
        entity_id (string): entity id

    Returns:
        string: entity name
    """
    for entity_name, entity_metadata in ENTITIES.items():
        read_id = entity_metadata.get('dtdlSchema', {}).get('@id')
        if entity_id == read_id:
            return entity_name
    return None


def get_relationship_name(source_entity_name, target_entity_name):
    """Gets relationship name from given source and target entities.

    Args:
        source_entity_name (string): source entity
        target_entity_name (string): target entity

    Returns:
        string: relationship name
    """
    target_entity_id = ENTITIES[target_entity_name].get(
        'dtdlSchema', {}).get('@id')
    contents = ENTITIES[source_entity_name].get(
        'dtdlSchema', {}).get('contents', [])
    relationships = [content for content in contents if content.get(
        '@type') == 'Relationship']
    for relationship in relationships:
        if relationship['target'] == target_entity_id:
            return relationship['name']
    return None


def get_target_entity_name(source_entity_name, relationship_name):
    """Gets target entity name from a given source entity and relationship name.

    Args:
        source_entity_name (string): source entity
        relationship_name (string): relationship name

    Returns:
        string: target entity name
    """
    contents = ENTITIES[source_entity_name].get(
        'dtdlSchema', {}).get('contents', [])
    relationships = [content for content in contents if content.get(
        '@type') == 'Relationship']
    for relationship in relationships:
        if relationship_name == relationship['name']:
            target_entity_id = relationship['target']
            target_entity_name = get_entity_name(entity_id=target_entity_id)
            return target_entity_name


def is_required_column(entity_name, column_name):
    """Checks if a given columns is required field of the entity or not.

    Args:
        entity_name (string): entity name
        column_name (string): column name to be checked

    Returns:
        boolean: if the column is required or not
    """
    entity_metadata = ENTITIES.get(entity_name)
    for column in entity_metadata["columns"]:
        if column["name"] == column_name:
            if column["primaryKey"] == "true":
                return True
            else:
                return False
    return False


def is_join_column_filter_match(join_column_filter, extracted_row):
    """Checks if the filter match with given row.

    Args:
        join_column_filter (string): filter
        extracted_row (dictionary): extracted row

    Returns:
        boolean: filter matches or not
    """
    if join_column_filter == '':
        return True

    join_column_filter_settings = join_column_filter.split("=")
    join_column_filter_name = join_column_filter_settings[0].strip()
    join_column_filter_value = join_column_filter_settings[1].replace(
        "'", "").strip()

    return extracted_row[join_column_filter_name] == join_column_filter_value


def get_concatenation_value(item, columns_string):
    """Concatenates given values.

    Args:
        item (dictionary): row
        columns_string (string): comma separated columns to join

    Returns:
        string: concatenated values
    """
    try:
        if is_split_required(columns_string):
            return format_split(item, columns_string)
        else:
            values = []
            columns = columns_string.split(",")
            current_value = item

            if not isinstance(current_value, (dict)):
                current_value = ast.literal_eval(current_value)
            for column in columns:
                value = get_value(item, column)
                # if value is a datetime, format date with DATE_FORMAT in order to benefit relationship data matching; otherwise keep value as is
                value = format_date(value)
                values.append(value)

            concatenation_value = "|".join(values)
            return concatenation_value
    except Exception as e:
        print(f"EXCEPTION {e}")
        return None


def prepare_relationships(relationship_list, source_join_field_values_primary_keys, target_join_field_values_primary_keys, entity_source_to_target_primary_keys, entityname_relationshipdictkey_dict):
    """Prepares relationships dictionary

    Args:
        relationship_list (dictionary): relationships extracted from the configuration file
        source_join_field_values_primary_keys (dictionary): primary keys of values coming from source files
        target_join_field_values_primary_keys (dictionary): primary keys of values coming from targer files
        entity_source_to_target_primary_keys (dictionary): dictionary of target primary key per source per entity
        entityname_relationshipdictkey_dict (dictionary): dictionary of relationships per entity

    Returns:
        dictionary: relationship dictionaries
    """
    # dictionary of source entity, target entity, join field, and relationship display name for each entity that has a relationship
    relationship_dict = {}
    for relationship in relationship_list:
        source_entity_name = relationship['source_entity_name']
        if source_entity_name not in source_join_field_values_primary_keys:
            # create dictionary of PrimaryKey per join field value per source entity
            source_join_field_values_primary_keys[source_entity_name] = {}
        if source_entity_name not in entity_source_to_target_primary_keys:
            # create dictionary of target PrimaryKey per source PrimaryKey per entity
            entity_source_to_target_primary_keys[source_entity_name] = {}

        target_entity_name = ''
        relationship_name = ''

        if 'target_entity_name' in relationship:
            target_entity_name = relationship['target_entity_name']
            relationship_name = get_relationship_name(
                source_entity_name, target_entity_name)
        else:
            relationship_name = relationship['relationship_name']
            target_entity_name = get_target_entity_name(
                source_entity_name, relationship_name)

        if target_entity_name not in target_join_field_values_primary_keys:
            # create dictionary of PrimaryKey per join field value per target entity
            target_join_field_values_primary_keys[target_entity_name] = {}

        # cache info needed to write mapping row
        source_join_column = relationship['source_join_column']
        target_join_column = relationship['target_join_column']
        source_join_column_filter = relationship['source_join_column_filter']
        target_join_column_filter = relationship['target_join_column_filter']
        source_file_name = relationship['source_file_name'] if 'source_file_name' in relationship else ''
        target_file_name = relationship['target_file_name'] if 'target_file_name' in relationship else ''

        relationshipdict_key = source_entity_name + "_" + target_entity_name

        if not source_entity_name in entityname_relationshipdictkey_dict:
            entityname_relationshipdictkey_dict[source_entity_name] = set()

        entityname_relationshipdictkey_dict[source_entity_name].add(
            relationshipdict_key)

        if not target_entity_name in entityname_relationshipdictkey_dict:
            entityname_relationshipdictkey_dict[target_entity_name] = set()

        entityname_relationshipdictkey_dict[target_entity_name].add(
            relationshipdict_key)

        if not relationshipdict_key in relationship_dict:
            relationship_dict[relationshipdict_key] = []

        relationship_dict[relationshipdict_key].append({
            "source_entity_name": source_entity_name,
            "target_entity_name": target_entity_name,
            "source_join_column": source_join_column,
            "target_join_column": target_join_column,
            "source_join_column_filter": source_join_column_filter,
            "target_join_column_filter": target_join_column_filter,
            "source_file_name": source_file_name,
            "target_file_name": target_file_name,
            "relationship_name": relationship_name,
            "sourcevalue_targetvalue_dict": {}
        })
    return relationship_dict, entityname_relationshipdictkey_dict


def write_csv(data, output_file):
    """Writes csv.

    Args:
        data (dictionary): data to be written
        output_file (string): output file path
    """
    try:
        df = pd.DataFrame.from_dict(data)
        if not df.empty:
            df.to_csv(output_file, index=False)
            print(f"MDS Data file {output_file} is created with length {df.shape[0]}")
    except:
        print(f"Can't write the file {output_file}")
        return


def write_entity_data(input_folder, output_folder, output_mapping_folder, entity_list, relationship_list):
    """Generates transformed data.

    Args:
        input_folder (string): directory of inputs
        output_folder (string): directory of outputs
        output_mapping_folder (string): directory of outputs for relationships
        entity_list (dictionary): entity list extracted from configuration file
        relationship_list (dictionary): relationships extracted from the configuration file

    Raises:
        StopIteration: in case invalid row/file
    """
    # dictionary of all join field values and their primary_keys for each entity that has a relationship
    source_join_field_values_primary_keys = {}
    target_join_field_values_primary_keys = {}

    # dictionary of source entity, target entity, join field, and relationship display name for each entity that has a relationship
    relationship_dict = {}
    relationships = {}

    # dictionary of entity source PrimaryKeys to entity target PrimaryKeys
    entity_source_to_target_primary_keys = {}

    # prep relationships
    entityname_relationshipdictkey_dict = {}
    if relationship_list:
        relationship_dict, entityname_relationshipdictkey_dict = prepare_relationships(
            relationship_list, source_join_field_values_primary_keys, target_join_field_values_primary_keys, entity_source_to_target_primary_keys, entityname_relationshipdictkey_dict)

    # create dictionary of relationships which holds output file names and list of relationships
    list_of_relationships = {}

    # create dictionary of entities which holds output file names and list of entities
    list_of_entities = {}

    # cache all data
    for entity in entity_list:
        entity_name = entity.get('entity_name')
        print(f"Processing entity: {entity_name}")
        primarykey_cache = set()

        # create list to store each mapped row as a dictionary for the entity
        list_of_rows = []

        for mapping in entity.get('mapping_list'):
            output_file = f"{output_folder}/{entity_name}_1.csv"

            # create dictionary of all mapped data for this entity
            to_field_names = []
            input_file_names = mapping.get('input_file_names')
            to_from_fields = mapping.get('to_from_fields')
            enums = mapping.get('enums')

            for to_field in to_from_fields.keys():
                if not to_field in to_field_names:
                    to_field_names.append(to_field)

            input_file_paths = f"{input_folder}/{input_file_names}"

            # write all mapped data for this entity
            to_field_names.insert(0, "PrimaryKey")
            input_file_name = os.path.basename(input_file_paths)
            try:
                # add encoding='utf-8-sig' in order to trim the "ï»¿" at the beginning of the csv file read
                with open(input_file_paths, 'r', encoding='utf-8-sig') as csv_file:
                    reader = csv.DictReader(csv_file)
                    for index, item in enumerate(reader):
                        try:
                            extracted_row = {"PrimaryKey": ""}
                            for to_field, from_field in to_from_fields.items():
                                
                                from_field_value = from_field
                                # get the mapped value
                                if is_split_required(from_field_value):
                                    from_field_value = format_split(item, from_field_value)
                                else:
                                    brace_enclosed_text_list = get_brace_enclosed_text(
                                        from_field)
                                    for brace_enclosed_text in brace_enclosed_text_list:
                                        value = get_brace_enclosed_value(
                                            item=item, substring=brace_enclosed_text)

                                        # skip if a required field is missing
                                        if not value and is_required_column(entity_name, to_field):
                                            raise StopIteration

                                        # skip if substitution did nothing
                                        if value == strip_enclosing_braces(from_field):
                                            raise StopIteration

                                        from_field_value = from_field_value.replace(
                                            brace_enclosed_text, value)

                                    # replace enum values
                                    if enums:
                                        enum_values = enums.get(from_field)
                                        if enum_values:
                                            to_field_value = enum_values.get(
                                                from_field_value)
                                            if to_field_value:
                                                from_field_value = to_field_value

                                # set the mapped value
                                extracted_row[to_field] = from_field_value

                            # add newly extracted row
                            primary_key = generate_primary_key(
                                extracted_row, entity_name)
                            extracted_row["PrimaryKey"] = primary_key

                            if entity_name in entityname_relationshipdictkey_dict:
                                keys = entityname_relationshipdictkey_dict[entity_name]
                                for key in keys:
                                    relationships = relationship_dict[key]
                                    for relationship in relationships:
                                        source_entity_name = relationship['source_entity_name']
                                        target_entity_name = relationship['target_entity_name']
                                        source_file_name = relationship[
                                            'source_file_name'] if 'source_file_name' in relationship else ''
                                        target_file_name = relationship[
                                            'target_file_name'] if 'target_file_name' in relationship else ''

                                        source_join_column_filter = relationship['source_join_column_filter']
                                        target_join_column_filter = relationship['target_join_column_filter']

                                        is_source_join_field = False
                                        if entity_name == source_entity_name and (source_file_name == '' or source_file_name == input_file_names) and is_join_column_filter_match(source_join_column_filter, extracted_row):
                                            join_field = relationship['source_join_column']
                                            is_source_join_field = True
                                        elif entity_name == target_entity_name and (target_file_name == '' or target_file_name == input_file_names) and is_join_column_filter_match(target_join_column_filter, extracted_row):
                                            join_field = relationship['target_join_column']
                                            is_source_join_field = False
                                        else:
                                            continue

                                        join_field_value = get_concatenation_value(
                                            item, join_field)
                                        
                                        if join_field_value:

                                            # cache PrimaryKey per join column value per entity
                                            if is_source_join_field:
                                                if not join_field_value in source_join_field_values_primary_keys[entity_name]:
                                                    source_join_field_values_primary_keys[entity_name][join_field_value + source_join_column_filter] = set()
                                                source_join_field_values_primary_keys[entity_name][join_field_value + source_join_column_filter].add(primary_key)
                                            else:
                                                if not join_field_value in target_join_field_values_primary_keys[entity_name]:
                                                    target_join_field_values_primary_keys[entity_name][join_field_value + target_join_column_filter] = set()
                                                target_join_field_values_primary_keys[entity_name][join_field_value + target_join_column_filter].add(primary_key)
                                            
                                            # check that a matching join field value can be found
                                            if (is_source_join_field and join_field_value + target_join_column_filter in target_join_field_values_primary_keys[target_entity_name]) or ((not is_source_join_field) and join_field_value + source_join_column_filter in source_join_field_values_primary_keys[source_entity_name]):
                                                source_primary_keys = []
                                                target_primary_keys = []
                                                if is_source_join_field:
                                                    source_primary_keys = [
                                                        primary_key]
                                                    target_primary_keys = target_join_field_values_primary_keys[target_entity_name][join_field_value + target_join_column_filter]
                                                elif entity_name == target_entity_name:
                                                    source_primary_keys = source_join_field_values_primary_keys[source_entity_name][join_field_value + source_join_column_filter]
                                                    target_primary_keys = [
                                                        primary_key]

                                                for source_primary_key in source_primary_keys:
                                                    for target_primary_key in target_primary_keys:

                                                        found = False
                                                        if source_primary_key in entity_source_to_target_primary_keys[source_entity_name]:
                                                            found = target_primary_key == entity_source_to_target_primary_keys[
                                                                source_entity_name][source_primary_key]
                                                        if not found:

                                                            # this is a new Source PrimaryKey to Target PrimaryKey
                                                            # cache new mapping
                                                            entity_source_to_target_primary_keys[source_entity_name][
                                                                source_primary_key] = target_primary_key

                                                            # write mapping row
                                                            mapping_output_file = f"{output_mapping_folder}/{source_entity_name}_to_{target_entity_name}_mapping_1.csv"
                                                            relationship_name = relationship['relationship_name']
                                                            mapping_row = {"Source type": source_entity_name, "Source PrimaryKey": source_primary_key,
                                                                           "Target Type": target_entity_name, "Target PrimaryKey": target_primary_key, "Relationship Type": relationship_name}
                                                            if mapping_output_file not in list_of_relationships:
                                                                list_of_relationships[mapping_output_file] = []
                                                            if mapping_row not in list_of_relationships[mapping_output_file]:
                                                                list_of_relationships[mapping_output_file].append(mapping_row)
                            if primary_key not in primarykey_cache:
                                list_of_rows.append(extracted_row)
                                primarykey_cache.add(primary_key)

                        except StopIteration:
                            pass
                        except Exception:
                            print(f"entity name: {entity_name}, file name: {input_file_name}, row: {index}, item: {item}")
                            sys.exit()
            except Exception:
                print(f"File {input_file_paths} can't be read, skipping")

        if len(list_of_rows) > 0:
            list_of_entities[output_file] = list_of_rows

    for entity_file in list_of_entities:
        try:
            write_csv(list_of_entities[entity_file], entity_file)
        except Exception:
            print(f"can't write the file: {entity_file}")
            continue

    for relationship_file in list_of_relationships:
        try:
            write_csv(
                list_of_relationships[relationship_file], relationship_file)
        except Exception:
            print(f"can't write the file: {relationship_file}")
            continue