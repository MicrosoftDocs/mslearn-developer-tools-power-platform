import io
import json
import re
import sys
import os
import time

import redis
import requests
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.data.tables import TableServiceClient
from azure.identity import AzureCliCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoApiError
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.cosmosdb import CosmosDBManagementClient
from azure.mgmt.cosmosdb.models import SqlContainerResource, ContainerPartitionKey, SqlContainerCreateUpdateParameters, \
    ThroughputSettingsResource, AutoscaleSettings, ThroughputSettingsUpdateParameters
from azure.mgmt.web import WebSiteManagementClient
from redis.exceptions import ResponseError

class FORMATTING_CONSTANTS:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    SUBPOINT = ' - '
    NEWLINE = '\n'

def cleanCosmos(cleanupConfig, isMasterReset = False):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Cosmos cleanup{FORMATTING_CONSTANTS.ENDC}")
    resource_group_name = cleanupConfig["resource_group_name"]
    database_account_name = cleanupConfig["cosmos_account_name"]
    database_name = cleanupConfig["cosmos_db_name"]
    credential = AzureCliCredential()
    subscription_id = cleanupConfig["subscription_id"]
    client = CosmosDBManagementClient(credential, subscription_id)
    collections = ["EntityStoreCollection"]
    if isMasterReset:
        collections.extend(["EntityMetadataCollection", "CopilotCollection"])
    for current_collection in collections:
        isContainerExists = checkCosmosContainer(client, resource_group_name, database_account_name, database_name, current_collection)
        if isContainerExists:
           deleteCosmosContainer(client, resource_group_name, database_account_name, database_name, current_collection)
        createCosmosContainer(client, resource_group_name, database_account_name, database_name, current_collection)
        upgradeCosmosContainerToAutoscale(client, resource_group_name, database_account_name, database_name, current_collection)
        if current_collection == "EntityStoreCollection":
           throughput = cleanupConfig["entitystore_collection_throughput"]
        else:
           throughput = 4000
        updateCosmosContainerThroughput(client, resource_group_name, database_account_name, database_name, current_collection, throughput)

    container_id = "CopilotCollection"
    cosmosClient = getCosmosContainerClient(database_account_name, database_name, container_id)
    for currentPartitionKey in ["AliasDictionaryMetadata", "InstructionDoc", "exampleQueryDoc"]:
        clearSpecificDocs(cosmosClient, currentPartitionKey)

    print(f"{FORMATTING_CONSTANTS.BOLD}Cosmos cleanup completed{FORMATTING_CONSTANTS.ENDC}")

def checkCosmosContainer(client, resource_group_name, database_account_name, database_name, container_name):
    print(f"{FORMATTING_CONSTANTS.OKBLUE}Checking if Cosmos container - {container_name} already exists or not{FORMATTING_CONSTANTS.ENDC}")
    for sql_container in client.sql_resources.list_sql_containers(account_name=database_account_name,
                                                                  resource_group_name=resource_group_name,
                                                                  database_name=database_name):
        if container_name == sql_container.name:
            print(f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Container - {container_name} exists{FORMATTING_CONSTANTS.ENDC}")
            return True
    print(f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.WARNING}Container - {container_name} doesn't exists{FORMATTING_CONSTANTS.ENDC}")
    return False


def deleteCosmosContainer(client, resource_group_name, database_account_name, database_name, container_name):
    print(f"{FORMATTING_CONSTANTS.OKBLUE}Deleting Exisitng Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    poller = client.sql_resources.begin_delete_sql_container(resource_group_name=resource_group_name,
                                                             account_name=database_account_name,
                                                             database_name=database_name,
                                                             container_name=container_name)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.BOLD}Deleting Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    printPollerStatus(poller)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Deleted Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")


def createCosmosContainer(client, resource_group_name, database_account_name, database_name, container_name):
    print(f"{FORMATTING_CONSTANTS.OKBLUE}Creating Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    store_collection_indexing_policy = {
        "indexingMode": "consistent",
        "automatic": True,
        "includedPaths": [
            {"path": "/'_rowId'/?"}
        ],
        "excludedPaths": [
            {"path": "/*"},
            {"path": "/'_etag'/?"}
        ]
    }
    metadata_collection_indexing_policy = {
        "indexingMode": "consistent",
        "automatic": True,
        "includedPaths": [
            {"path": "/*"}
        ],
        "excludedPaths": [
            {"path": "/'_etag'/?"}
        ]
    }
    if container_name == "EntityStoreCollection":
        collection_indexing_policy = store_collection_indexing_policy
    else:
        collection_indexing_policy = metadata_collection_indexing_policy
    container_properties = SqlContainerResource(
        id=container_name,
        partition_key=ContainerPartitionKey(
            paths=["/partitionKey"]
        ),
        indexing_policy=collection_indexing_policy
    )
    parameters = SqlContainerCreateUpdateParameters(
        resource=container_properties
    )

    poller = client.sql_resources.begin_create_update_sql_container(resource_group_name=resource_group_name,
                                                                    account_name=database_account_name,
                                                                    database_name=database_name,
                                                                    container_name=container_name,
                                                                    create_update_sql_container_parameters=parameters)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.BOLD}Creating Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    printPollerStatus(poller)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Created Cosmos Container - {container_name}{FORMATTING_CONSTANTS.ENDC}")


def upgradeCosmosContainerToAutoscale(client, resource_group_name, database_account_name, database_name,
                                      container_name):
    print(f"{FORMATTING_CONSTANTS.OKBLUE}Enabling autoscale on container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    poller = client.sql_resources.begin_migrate_sql_container_to_autoscale(resource_group_name=resource_group_name,
                                                                           account_name=database_account_name,
                                                                           database_name=database_name,
                                                                           container_name=container_name)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.BOLD}Enabling autoscale on container  - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    printPollerStatus(poller)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Enabled autoscale on container  - {container_name}{FORMATTING_CONSTANTS.ENDC}")

def updateCosmosContainerThroughput(client, resource_group_name, database_account_name, database_name, container_name, throughput):
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Updating Throughput on container - {container_name}{FORMATTING_CONSTANTS.ENDC}")    
    autoscale_throughput = ThroughputSettingsResource(
        autoscale_settings=AutoscaleSettings(max_throughput=throughput)
    )
    throughput_settings = ThroughputSettingsUpdateParameters(resource=autoscale_throughput)
    poller = client.sql_resources.begin_update_sql_container_throughput(resource_group_name=resource_group_name,
                                                                        account_name=database_account_name,
                                                                        database_name=database_name,
                                                                        container_name=container_name,
                                                                        update_throughput_parameters=throughput_settings)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.BOLD}Updating Throughput on container - {container_name}{FORMATTING_CONSTANTS.ENDC}")
    printPollerStatus(poller)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Updated Throughput on container - {container_name}{FORMATTING_CONSTANTS.ENDC}")

def getCosmosContainerClient(database_account_name, database_name, container_id):
    credential = AzureCliCredential()
    endpoint = f"https://{database_account_name}.documents.azure.com:443/"
    client = CosmosClient(url=endpoint, credential=credential)
    database_id = database_name
    database_client = client.get_database_client(database_id)
    # Get a container client
    container_client = database_client.get_container_client(container_id)
    return container_client

def clearSpecificDocs(container_client, partitionKey):
    container_id = "CopilotCollection"
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Clearing Docs from collection - {container_id} with partitionKey - {partitionKey} {FORMATTING_CONSTANTS.ENDC}")
    # credential = AzureCliCredential()
    # endpoint = f"https://{database_account_name}.documents.azure.com:443/"
    # client = CosmosClient(url=endpoint, credential=credential)
    # database_id = database_name
    # database_client = client.get_database_client(database_id)
    # # Get a container client
    # container_client = database_client.get_container_client(container_id)
    partition_key_value = partitionKey
    query = "SELECT * FROM c WHERE c.partitionKey = @partitionKey"
    parameters = [
        {"name": "@partitionKey", "value": partition_key_value}
    ]

    # Run the query and get the results
    items = container_client.query_items(
        query=query,
        parameters=parameters,
        partition_key=partition_key_value
    )

    for item in items:
        docId = item["id"]
        print(f"{FORMATTING_CONSTANTS.SUBPOINT}Deleting doc with id : {docId}{FORMATTING_CONSTANTS.ENDC}")
        container_client.delete_item(item, str(item["partitionKey"]))
        print(f"{FORMATTING_CONSTANTS.SUBPOINT}Deleted doc with id : {docId}{FORMATTING_CONSTANTS.ENDC}")

def printPollerStatus(poller):
    dot_count = 0
    max_dots = 10
    while not poller.done():
        print(f"\r{FORMATTING_CONSTANTS.SUBPOINT}{poller.status()}{'.' * dot_count}{FORMATTING_CONSTANTS.ENDC}", end='')
        dot_count = (dot_count + 1) % (max_dots + 1)
        time.sleep(10)
        print(f"\r\033[K", end='')
    print(f"\r{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.BOLD}{poller.status()}{FORMATTING_CONSTANTS.ENDC}")

def cleanAdx(cleanupConfig, isMasterReset = False):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}ADX Cleanup{FORMATTING_CONSTANTS.ENDC}")
    cluster = cleanupConfig["adx_cluster_url"]
    adx_scope = f"{cluster}/.default"
    db = cleanupConfig["adx_db_name"]
    credential = AzureCliCredential()
    token = credential.get_token(adx_scope)
    token = token.token
    kcsb = KustoConnectionStringBuilder.with_aad_application_token_authentication(connection_string=cluster,
                                                                                  application_token=token)
    kusto_client = KustoClient(kcsb)
    tablenamesInAdx, contextTables = findAllTables(kusto_client, db)
    continousExports = findAllContinousExport(kusto_client, db)
    disableContinousExport(kusto_client, db, continousExports)
    clearAdxTables(kusto_client, db, tablenamesInAdx)

    if isMasterReset:
       clearAdxTables(kusto_client, db, contextTables)
    else:
        for contextTable in contextTables:
            print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Clearing Custom Context table - {contextTable}{FORMATTING_CONSTANTS.ENDC}")
            recordsFilterExpr = 'where Key startswith "Custom"'
            clearCustomContext(kusto_client, db, contextTable, recordsFilterExpr)
    enableContinousExport(kusto_client, db, continousExports)
    print(f"{FORMATTING_CONSTANTS.BOLD}ADX Cleanup completed{FORMATTING_CONSTANTS.ENDC}")


def findAllTables(kusto_client, db):
    cmd = ".show tables"
    response = kusto_client.execute(db, cmd)
    results = response.primary_results[0]
    rows = results.rows
    tableNames = set()
    contextTables = set()
    for row in rows:
        if str(row["TableName"]) == "AliasDictionary_VectorStore" or \
           str(row["TableName"]) == "Instructions_VectorStore":
            contextTables.add(row["TableName"])
        else:
            tableNames.add(row["TableName"])
    print(f"Exisitng Tables in ADX are - {tableNames}")
    print(f"Exisitng Context Tables in ADX are - {contextTables}")
    return tableNames, contextTables


def findAllContinousExport(kusto_client, db):
    cmd = ".show continuous-exports"
    response = kusto_client.execute(db, cmd)
    results = response.primary_results[0]
    rows = results.rows
    continousExportNames = set()
    for row in rows:
        continousExportNames.add(row["Name"])
    print(f"Exisitng Continous exports in ADX are - {continousExportNames}")
    return continousExportNames


def disableContinousExport(kusto_client, db, continousExportNames):
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Disabling Continous Exports{FORMATTING_CONSTANTS.ENDC}")
    for continousExportName in continousExportNames:
        try:
            cmd = f".disable continuous-export {continousExportName}"
            response = kusto_client.execute(db, cmd)
            results = response.primary_results[0]
            rows = results.rows
            for row in rows:
                isDisabled = row["IsDisabled"]
                print(
                    f"{FORMATTING_CONSTANTS.OKGREEN} - Continous Export - {continousExportName} , Disabled - {isDisabled}{FORMATTING_CONSTANTS.ENDC}")
        except KustoApiError as Ex:
            errorDescription = Ex.error.description
            if "already disabled" in str(errorDescription):
                print(
                    f"{FORMATTING_CONSTANTS.WARNING} - Continous Export - {continousExportName} , Already Disabled{FORMATTING_CONSTANTS.ENDC}")


def enableContinousExport(kusto_client, db, continousExportNames):
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Enabling Continous Exports{FORMATTING_CONSTANTS.ENDC}")
    for continousExportName in continousExportNames:
        try:
            cmd = f".enable continuous-export {continousExportName}"
            response = kusto_client.execute(db, cmd)
            results = response.primary_results[0]
            rows = results.rows
            for row in rows:
                isDisabled = row["IsDisabled"]
                print(
                    f"{FORMATTING_CONSTANTS.OKGREEN} - Continous Export - {continousExportName} , Disabled - {isDisabled}{FORMATTING_CONSTANTS.ENDC}")
        except KustoApiError as Ex:
            errorDescription = Ex.error.description
            if "already enabled" in str(errorDescription):
                print(
                    f"{FORMATTING_CONSTANTS.WARNING} - Continous Export - {continousExportName} , Already Enabled {FORMATTING_CONSTANTS.ENDC}")

def clearCustomContext(kusto_client, db, tableName, filter=""):
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}Clearing Custom context in table - {tableName} {FORMATTING_CONSTANTS.ENDC}")
    #cmd = f'.delete table {tableName} records <| {tableName} | where Key startswith "Custom"'
    cmd = f'.delete table {tableName} records <| {tableName} | {filter}'
    try:
        response = kusto_client.execute(db, cmd)
        results = response.primary_results[0]
        rows = results.rows
        if len(rows) == 0:
            print(
                f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.WARNING}No Custom context exisits in table - {tableName} {FORMATTING_CONSTANTS.ENDC}")
        else:
            records = rows[0]["RecordsMatchPredicate"]
            print(
                f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Cleared {records} Custom context records in table - {tableName} {FORMATTING_CONSTANTS.ENDC}")

    except KustoApiError as Ex:
        print(f"{FORMATTING_CONSTANTS.FAIL}{FORMATTING_CONSTANTS.UNDERLINE}Failed to Clear Custom context on table - {tableName}{FORMATTING_CONSTANTS.ENDC}")
        print(f"{FORMATTING_CONSTANTS.FAIL}{Ex.error.description}{FORMATTING_CONSTANTS.ENDC}")

    except Exception as Ex:
        print(
            f"{FORMATTING_CONSTANTS.FAIL}{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Failed to clear session doc from Copilot collection - {Ex}{FORMATTING_CONSTANTS.ENDC}")

def clearAdxTables(kusto_client, db, tableNames):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Clearing Each tables {FORMATTING_CONSTANTS.ENDC}")
    for tableName in tableNames:
        cmd = f".clear table {tableName} data"
        response = kusto_client.execute(db, cmd)
        results = response.primary_results[0]
        rows = results.rows
        for row in rows:
             status = row["Status"]
             if status == "Success":
                 print(f"{FORMATTING_CONSTANTS.OKGREEN} - Clearing status of table {tableName} is {status}{FORMATTING_CONSTANTS.ENDC}")

def cleanRedis(cleanupConfig, isMasterReset=False):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Redis cleanup{FORMATTING_CONSTANTS.ENDC}")
    redis_host = cleanupConfig["redis_host"]
    credential = AzureCliCredential()
    token = credential.get_token("https://redis.azure.com/.default")
    token = token.token
    objectId = findUserObjectId()
    try:
        redis_client = redis.StrictRedis(host=redis_host, port=6380, username=objectId, password=token, ssl=True,
                                         decode_responses=True)
        keysToDelete = list()
        keyPrefixes = ["MappedEntityDataPrefix*", "CopilotGenerativeDataContextPrefix*", "OpcuaMetadataPrefix*", "OpcuaMappingPrefix*", "CopilotConversationsPrefix*"]
        if isMasterReset:
            keyPrefixes.extend(["EntityMetadataPrefix*", "EntityNamesListPrefix", "TextChunksPrefix*"])
        for currentPrefix in keyPrefixes:
            keys = redis_client.keys(currentPrefix)
            for key in keys:
                keysToDelete.append(key)

        print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Deleting keys{FORMATTING_CONSTANTS.ENDC}")
        if len(keysToDelete) == 0:
            print(
                f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.WARNING}No Key exists to delete{FORMATTING_CONSTANTS.ENDC}")
            return
        for key in keysToDelete:
            redis_client.delete(key)
            print(
                f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Deleted Key - {key}{FORMATTING_CONSTANTS.ENDC}")
    except (ResponseError, Exception) as Ex:
        print(
            f"{FORMATTING_CONSTANTS.FAIL}{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Failed to clear Redis keys{FORMATTING_CONSTANTS.ENDC}")
        print(f"{FORMATTING_CONSTANTS.FAIL}{Ex}{FORMATTING_CONSTANTS.ENDC}")

    print(f"{FORMATTING_CONSTANTS.BOLD}Redis cleanup Completed{FORMATTING_CONSTANTS.ENDC}")


def findUserObjectId():
    credential = AzureCliCredential()
    token = credential.get_token('https://graph.microsoft.com/.default')
    graph_api_url = 'https://graph.microsoft.com/v1.0/me'
    headers = {'Authorization': f'Bearer {token.token}'}
    response = requests.get(graph_api_url, headers=headers)
    if response.status_code == 200:
        user_details = response.json()
        object_id = user_details.get('id')
        print(f"The object ID is: {FORMATTING_CONSTANTS.BOLD}{object_id}{FORMATTING_CONSTANTS.ENDC}")
        return object_id
    else:
        print(
            f"{FORMATTING_CONSTANTS.FAIL}Failed to retrieve user details. Status code: {response.status_code}, Response: {response.text}{FORMATTING_CONSTANTS.ENDC}")
        return ""


def cleanTables(cleanupConfig):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Tables cleanup{FORMATTING_CONSTANTS.ENDC}")
    bjsSaEndpoint = cleanupConfig["bjs_storage_account_url"]
    bjsTables = findAllTablesInBjsSa(bjsSaEndpoint)
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Deleting tables from BJS Storage Account{FORMATTING_CONSTANTS.ENDC}")
    deleteTablesFromSa(bjsSaEndpoint, bjsTables)
    funcAppSaEndpoint = cleanupConfig["function_app_storage_account_url"]
    funcAppTables = findAllTablesInBjsSa(funcAppSaEndpoint)
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKBLUE}Deleting tables from Function App Storage Account{FORMATTING_CONSTANTS.ENDC}")
    deleteTablesFromSa(funcAppSaEndpoint, funcAppTables)
    print(f"{FORMATTING_CONSTANTS.BOLD}Tables cleanup Completed{FORMATTING_CONSTANTS.ENDC}")


def findAllTablesInBjsSa(endpoint):
    service = TableServiceClient(endpoint=endpoint,
                                 credential=AzureCliCredential())
    table_names = [table.name for table in service.list_tables()]
    return set(table_names)


def deleteTablesFromSa(endpoint, tables):
    service = TableServiceClient(endpoint=endpoint,
                                 credential=AzureCliCredential())
    if len(tables) == 0:
        print(f"{FORMATTING_CONSTANTS.WARNING} - No Tables to Delete {FORMATTING_CONSTANTS.ENDC}")
    for table in tables:
        service.delete_table(table)
        print(
            f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Deleted table - {table}{FORMATTING_CONSTANTS.ENDC}")


def readCleanupConfig(isMasterReset):
    filePtr = open('config.json')
    cleanupConfiguration = json.load(filePtr)
    requiredParams = ["subscription_id", "resource_group_name", "cosmos_account_name", "cosmos_db_name",
                      "adx_cluster_url", "adx_db_name", "redis_host","aks_cluster_name"]
    if isMasterReset:
        hardResetParams = ["bjs_storage_account_url", "function_app_storage_account_url"]
        requiredParams.extend(hardResetParams)
    if not isMasterReset:
        cleanupConfiguration.pop("bjs_storage_account_url")
        cleanupConfiguration.pop("function_app_storage_account_url")
    for currentConfigParam in requiredParams:
        if currentConfigParam in cleanupConfiguration and cleanupConfiguration[currentConfigParam] == "" or \
                containsPlaceholder(cleanupConfiguration[currentConfigParam]):
            cleanupConfiguration[currentConfigParam] = readFromInteractive(currentConfigParam)
    if "entitystore_collection_throughput" not in cleanupConfiguration:
        print(f"{FORMATTING_CONSTANTS.WARNING}The throughput value for the EntityStoreCollection is not specified in the configuration, therefore it will be set to the default value of 10000.{FORMATTING_CONSTANTS.ENDC}")
        cleanupConfiguration["entitystore_collection_throughput"] = 10000
    return cleanupConfiguration


def containsPlaceholder(str):
    pattern = r"<[^>]*>"
    match = re.search(pattern, str)
    return bool(match)

def readFromInteractive(configParameter):
    value = input(
        f"{FORMATTING_CONSTANTS.BOLD}Since \'{configParameter}\' value is missing from config file or it has empty value Please enter valid value : {FORMATTING_CONSTANTS.ENDC}")
    return value

def aksStop(cleanupConfig):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Stopping AKS{FORMATTING_CONSTANTS.ENDC}")
    subscription_id = cleanupConfig["subscription_id"]
    resource_group_name = cleanupConfig["resource_group_name"]
    aks_cluster_name = cleanupConfig["aks_cluster_name"]
    credential = AzureCliCredential()
    client = ContainerServiceClient(credential, subscription_id)
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Stopping AKS Cluster - {aks_cluster_name}{FORMATTING_CONSTANTS.ENDC}")
    try:
        poller = client.managed_clusters.begin_stop(resource_group_name, aks_cluster_name)
        printPollerStatus(poller)
        print(
            f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}AKS Cluster Stopped !! {FORMATTING_CONSTANTS.ENDC}")
    except Exception as Ex:
        print(f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.WARNING}{Ex.exc_msg}{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")

def aksStart(cleanupConfig):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Starting AKS{FORMATTING_CONSTANTS.ENDC}")
    subscription_id = cleanupConfig["subscription_id"]
    resource_group_name = cleanupConfig["resource_group_name"]
    aks_cluster_name = cleanupConfig["aks_cluster_name"]
    credential = AzureCliCredential()
    client = ContainerServiceClient(credential, subscription_id)
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Starting AKS Cluster - {aks_cluster_name}{FORMATTING_CONSTANTS.ENDC}")
    try:
        poller = client.managed_clusters.begin_start(resource_group_name, aks_cluster_name)
        printPollerStatus(poller)
        print(
            f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}AKS Cluster Started !!{FORMATTING_CONSTANTS.ENDC}")
    except Exception as Ex:
        print(f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.WARNING}{Ex.exc_msg}{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")

def stopFunctionApp(cleanupConfig):
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Stopping Function App{FORMATTING_CONSTANTS.ENDC}")
    subscription_id = cleanupConfig["subscription_id"]
    resource_group_name = cleanupConfig["resource_group_name"]
    function_app_name = cleanupConfig["function_app_name"]
    credentials = AzureCliCredential()
    client = WebSiteManagementClient(credentials, subscription_id)
    client.web_apps.stop(resource_group_name, function_app_name)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Function App Stopped !!{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")

def startFunctionApp(cleanupConfig):
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Starting Function App{FORMATTING_CONSTANTS.ENDC}")
    subscription_id = cleanupConfig["subscription_id"]
    resource_group_name = cleanupConfig["resource_group_name"]
    function_app_name = cleanupConfig["function_app_name"]
    credentials = AzureCliCredential()
    client = WebSiteManagementClient(credentials, subscription_id)
    client.web_apps.start(resource_group_name, function_app_name)
    print(
        f"{FORMATTING_CONSTANTS.SUBPOINT}{FORMATTING_CONSTANTS.OKGREEN}Function App Started !!{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")

## resatart copilot pod and worker service 
def restartCopilotServices(cleanupConfig):
    resource_group_name = cleanupConfig["resource_group_name"]
    aks_cluster_name = cleanupConfig["aks_cluster_name"]
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Restarting the Copilot Services{FORMATTING_CONSTANTS.ENDC}")
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Restarting Copilot Server{FORMATTING_CONSTANTS.ENDC}")
    aks = "aks-cluster-mci4m-qoltfa5cmhjq4"
    rg = "dmm-copilot-l2-gpt32k-bakery-eastus2"
    cmd = f'az aks command invoke -n {aks_cluster_name} -g {resource_group_name} --command "kubectl rollout restart deployment/aks-dmmcopilot -n aks-dmm-copilot"'
    output = os.popen(cmd).read()
    output = ansi_escape.sub('', output)
    print(output)
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Restarting Copilot Worker Service {FORMATTING_CONSTANTS.ENDC}")
    cmd = f'az aks command invoke -n {aks_cluster_name} -g {resource_group_name} --command "kubectl rollout restart deployment/aks-dmmcopilotworker -n aks-dmm-copilot"'
    output = os.popen(cmd).read()
    output = ansi_escape.sub('', output)
    print(output)
    print(
        f"{FORMATTING_CONSTANTS.OKBLUE}Retrieving Status of Copilot Services {FORMATTING_CONSTANTS.ENDC}")
    cmd = f'az aks command invoke -n {aks_cluster_name} -g {resource_group_name} --command "kubectl get pods -n aks-dmm-copilot"'
    output = os.popen(cmd).read()
    output = ansi_escape.sub('', output)
    print(output)
    print(
        f"{FORMATTING_CONSTANTS.OKGREEN}Restarted the Copilot Services{FORMATTING_CONSTANTS.ENDC}")


if __name__ == "__main__":
    print(
        f"{FORMATTING_CONSTANTS.BOLD}The script performs cleanup on Cosmos DB, Azure Data Explorer, Redis cache, and Azure Storage tables.{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Clean slate{FORMATTING_CONSTANTS.ENDC}", end="")
    print(
        f"{FORMATTING_CONSTANTS.BOLD} - this will restore the system to its state prior to ingestion.{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Master reset{FORMATTING_CONSTANTS.ENDC}", end="")
    print(
        f"{FORMATTING_CONSTANTS.BOLD} - this process will revert the system to its original state, as if it were a fresh installation.[REQUIRES AKS CLUSTER RESTART]{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.BOLD}Please choose from the following clean-up options.{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.BOLD} 1. Clean slate{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.BOLD} 2. Master reset{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    isMasterReset = False
    while (True):
        cleanupSelection = input("Enter your choice : ")
        if cleanupSelection == "1":
            print(f"{FORMATTING_CONSTANTS.BOLD}Performing Clean slate!!!{FORMATTING_CONSTANTS.ENDC}")
            break
        elif cleanupSelection == "2":
            print(f"{FORMATTING_CONSTANTS.BOLD}Performing Master reset!!!{FORMATTING_CONSTANTS.ENDC}")
            isMasterReset = True
            break
        else:
            print(f"Invalid Selection {cleanupSelection}, Please Select either 1 or 2")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    cleanupConfig = readCleanupConfig(isMasterReset)
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.UNDERLINE}Using below config for cleanup {FORMATTING_CONSTANTS.ENDC}")
    for key, value in cleanupConfig.items():
        print(f"{FORMATTING_CONSTANTS.SUBPOINT}{key} : {FORMATTING_CONSTANTS.BOLD}{value}{FORMATTING_CONSTANTS.ENDC}")
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    confirmMsg = input(
        f"{FORMATTING_CONSTANTS.BOLD}Please confirm if the provided configuration is accurate: [yes]/[no] : {FORMATTING_CONSTANTS.ENDC}")
    if confirmMsg not in ["yes", "y"]:
        print(f"{FORMATTING_CONSTANTS.FAIL}Exiting the cleanup script{FORMATTING_CONSTANTS.ENDC}")
        sys.exit()
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")

    if isMasterReset:
        print(
            f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.WARNING}AKS Cluster should be stopped before Master reset!! {FORMATTING_CONSTANTS.ENDC}")
        flag = input(
            f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.WARNING}Stop AKS Cluster [yes]/[no] : {FORMATTING_CONSTANTS.ENDC}").lower()
        if flag in ["yes", "y"]:
            print(
                f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.WARNING}Consent received - {flag}!!!{FORMATTING_CONSTANTS.ENDC}")
            print(f"{FORMATTING_CONSTANTS.NEWLINE}")
            aksStop(cleanupConfig)
        else:
            print(
                f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.WARNING}Consent received - {flag}, Exiting!!!{FORMATTING_CONSTANTS.ENDC}")
            exit()
    stopFunctionApp(cleanupConfig)
    cleanCosmos(cleanupConfig, isMasterReset)
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    cleanAdx(cleanupConfig)
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    cleanRedis(cleanupConfig, isMasterReset)
    print(f"{FORMATTING_CONSTANTS.NEWLINE}")
    if isMasterReset:
        cleanTables(cleanupConfig)
        print(f"{FORMATTING_CONSTANTS.NEWLINE}")
        aksStart(cleanupConfig)
    else:
        restartCopilotServices(cleanupConfig)
    startFunctionApp(cleanupConfig)
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.OKGREEN}CLEANUP IS COMPLETED!!!{FORMATTING_CONSTANTS.ENDC}")
    print(
        f"{FORMATTING_CONSTANTS.BOLD}{FORMATTING_CONSTANTS.WARNING}Note: If Copilot is enabled, please wait 15-20 minutes for the inbuilt context to be restored.{FORMATTING_CONSTANTS.ENDC}")