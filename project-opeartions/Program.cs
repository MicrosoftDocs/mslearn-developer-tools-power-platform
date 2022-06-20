using Microsoft.Xrm.Sdk;
using Microsoft.Xrm.Sdk.Query;
using Microsoft.Xrm.Tooling.Connector;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.Serialization;

namespace MSLearn.ProjectScheduleApi
{
    class Program
    {
        static IOrganizationService organizationService;
        static LegacyData data;

        static void Main(string[] args)
        {
            InitializeLegacyData();
            InitializeOrganizationService();

            PrintHeader("Create Accounts");
            foreach (var legacyAccount in data.Accounts)
            {
                CreateAccount(legacyAccount);
            }

            PrintHeader("Create Resources");
            foreach (var legacyContact in data.Resources)
            {
                Entity contact = CreateContact(legacyContact);
                CreateBookableResource(legacyContact, contact);
            }

            PrintHeader("Create Bookable Resource categories");
            Entity ProjectManagerResource = CreatePMResource();
            Entity TeamMemberResource = CreateTeamMemberResource();


            PrintHeader("Create Projects");
            foreach (var legacyProject in data.Projects)
            {
                Entity project = CreateProject(legacyProject);
                var projectReference = project.ToEntityReference();

                // create team members associated with the project
                foreach (var legacyProjectTeam in data.ProjectTeams
                    .Where(x => x.ProjectId == legacyProject.ProjectId))
                {
                    CreateTeamMember(
                        ProjectManagerResource,
                        TeamMemberResource,
                        projectReference,
                        legacyProjectTeam);
                }

                // Create operation set to include all the tasks, dependencies and assignments
                var description = $"{legacyProject.Name} - {DateTime.Now.ToShortTimeString()}";
                var operationSetId = CallCreateOperationSetAction(project.Id, description);

                // Create tasks and assignment
                foreach (var legacyTask in data.Tasks
                    .Where(x => x.ProjectId == legacyProject.ProjectId))
                {
                    Entity task = AddTaskToOperationSet(
                        projectReference,
                        operationSetId,
                        legacyTask);

                    // Find assignment for the task. To keep the scenario simple 
                    // there is only one assignment per task.
                    var legacyAssignment = data.Assignments
                        .FirstOrDefault(x => x.TaskId == legacyTask.TaskId);
                    if (legacyAssignment != null)
                    {
                        AddAssignmentToOperationSet(
                            legacyProject,
                            project,
                            operationSetId,
                            legacyTask,
                            task,
                            legacyAssignment);
                    }
                }

                // create task dependencies
                foreach (var legacyDependency in data.Dependencies
                    .Where(x => x.ProjectId == legacyProject.ProjectId))
                {
                    AddDependencyToOperationSet(
                        project,
                        operationSetId,
                        legacyDependency);
                }

                CallExecuteOperationSetAction(operationSetId);
            }

            Console.WriteLine("Migration finished. Press any key to continue...");
            Console.ReadLine();
        }

        #region Record creation helpers
        /// <summary>
        /// Adds a task dependency to the operation set 
        /// </summary>
        /// <param name="project">Project</param>
        /// <param name="operationSetId">Id of the operation set</param>
        /// <param name="legacyDependency">Legacy dependency</param>
        static void AddDependencyToOperationSet(
            Entity project,
            string operationSetId,
            LegacyTaskDependency legacyDependency)
        {
            var taskDependency = new Entity("msdyn_projecttaskdependency", Guid.NewGuid());
            taskDependency["msdyn_project"] = project.ToEntityReference();
            taskDependency["msdyn_predecessortask"] = (data.Tasks.First(x => x.TaskId == legacyDependency.Task1Id)).Reference;
            taskDependency["msdyn_successortask"] = (data.Tasks.First(x => x.TaskId == legacyDependency.Task2Id)).Reference;
            taskDependency["msdyn_linktype"] = new OptionSetValue(192350000);
            CallPssCreateAction(taskDependency, operationSetId);
            PrintInfo(legacyDependency.Task1Id + " --> " + legacyDependency.Task2Id, taskDependency);
        }

        /// <summary>
        /// Adds assignment record to the operation set
        /// </summary>
        /// <param name="legacyProject">Legacy project</param>
        /// <param name="project">Project</param>
        /// <param name="operationSetId">Id of the operation set</param>
        /// <param name="legacyTask">Legacy task</param>
        /// <param name="task">Task</param>
        /// <param name="legacyAssignment">Legacy Assignment</param>
        static void AddAssignmentToOperationSet(
            LegacyProject legacyProject,
            Entity project,
            string operationSetId,
            LegacyTask legacyTask,
            Entity task,
            LegacyAssignment legacyAssignment)
        {
            var assignment = new Entity("msdyn_resourceassignment", Guid.NewGuid());
            assignment["msdyn_projectteamid"] = data.ProjectTeams
                .First(x => x.ResourceId == legacyAssignment.ResourceId
                && x.ProjectId == legacyProject.ProjectId).Reference;
            assignment["msdyn_taskid"] = task.ToEntityReference();
            assignment["msdyn_projectid"] = project.ToEntityReference();
            assignment["msdyn_name"] = $"Assignment: ${legacyTask.Name}";
            CallPssCreateAction(assignment, operationSetId);
            PrintInfo(legacyAssignment.ResourceId, assignment);
        }

        /// <summary>
        /// Adds a task to the operation set
        /// </summary>
        /// <param name="projectReference">Project reference</param>
        /// <param name="operationSetId">Id of the operation set</param>
        /// <param name="legacyTask">Legacy Task</param>
        /// <returns>Task</returns>
        static Entity AddTaskToOperationSet(
            EntityReference projectReference,
            string operationSetId,
            LegacyTask legacyTask)
        {
            var task = new Entity("msdyn_projecttask", Guid.NewGuid());
            task["msdyn_project"] = projectReference;
            task["msdyn_subject"] = legacyTask.Name;
            task["msdyn_duration"] = legacyTask.Duration;
            task["msdyn_scheduledstart"] = DateTime.Today;
            task["msdyn_scheduledend"] = DateTime.Today.AddDays(legacyTask.Duration);
            task["msdyn_start"] = DateTime.Now.AddDays(1);
            task["msdyn_projectbucket"] = GetBucket(projectReference).ToEntityReference();
            task["msdyn_LinkStatus"] = new OptionSetValue(192350000);

            if (legacyTask.ParentTaskId == "")
            {
                task["msdyn_outlinelevel"] = 1;
            }
            else
            {
                task["msdyn_parenttask"] = data.Tasks.First(x => x.TaskId == legacyTask.ParentTaskId).Reference;
            }

            CallPssCreateAction(task, operationSetId);
            legacyTask.Reference = task.ToEntityReference();
            PrintInfo(legacyTask.TaskId, task);
            return task;
        }

        /// <summary>
        /// Creates a team member using the action
        /// </summary>
        /// <param name="projectManagerResource">Project manager bookable resource category</param>
        /// <param name="teamMemberResource">Team member bookable resource category</param>
        /// <param name="projectReference">Project reference</param>
        /// <param name="legacyProjectTeam">Legacy project team</param>
        static void CreateTeamMember(
            Entity projectManagerResource,
            Entity teamMemberResource,
            EntityReference projectReference,
            LegacyProjectTeam legacyProjectTeam)
        {
            var teamMember = new Entity("msdyn_projectteam", Guid.NewGuid());
            var resource = data.Resources.First(x => x.ResourceId == legacyProjectTeam.ResourceId);
            teamMember["msdyn_name"] = $"{legacyProjectTeam.Role} 1";
            teamMember["msdyn_project"] = projectReference;
            teamMember["msdyn_bookableresourceid"] = resource.BookableReference;
            teamMember["msdyn_resourcecategory"] = legacyProjectTeam.Role == "Project Manager" ?
                projectManagerResource.ToEntityReference() : teamMemberResource.ToEntityReference();
            teamMember["msdyn_projectapprover"] = legacyProjectTeam.Role == "Project Manager";
            teamMember.Id = CallCreateTeamMemberAction(teamMember);
            legacyProjectTeam.Reference = teamMember.ToEntityReference();
            PrintInfo(legacyProjectTeam.ResourceId, teamMember);
        }

        /// <summary>
        /// Creates a project using the action
        /// </summary>
        /// <param name="legacyProject">Legacy Project</param>
        /// <returns>Project</returns>
        private static Entity CreateProject(LegacyProject legacyProject)
        {
            var project = new Entity("msdyn_project");
            project["msdyn_subject"] = legacyProject.Name;
            project["msdyn_description"] = legacyProject.Description;

            // Set the customer as the entity reference
            project["msdyn_customer"] = data.Accounts.First(x => x.AccountId == legacyProject.AccountId).Reference;

            project.Id = CallCreateProjectAction(project);
            PrintInfo(legacyProject.ProjectId, project);
            return project;
        }

        /// <summary>
        /// Creates a Team member bookable resource category
        /// </summary>
        /// <returns>Bookable resource category</returns>
        static Entity CreateTeamMemberResource()
        {
            var TMResource = new Entity("bookableresourcecategory");
            TMResource["name"] = "Team Member";
            TMResource.Id = organizationService.Create(TMResource);
            PrintInfo("Team Member", TMResource);
            return TMResource;
        }

        /// <summary>
        /// Creates a Project manager bookable resource category
        /// </summary>
        /// <returns>Bookable resource category</returns>
        static Entity CreatePMResource()
        {
            var PMResource = new Entity("bookableresourcecategory");
            PMResource["name"] = "Project Manager";
            PMResource.Id = organizationService.Create(PMResource);
            PrintInfo("Project Manger", PMResource);
            return PMResource;
        }

        /// <summary>
        /// Creates an account
        /// </summary>
        /// <param name="legacyAccount">Legacy account</param>
        static void CreateAccount(LegacyAccount legacyAccount)
        {
            var account = new Entity("account");
            account["name"] = legacyAccount.Name;
            account["telephone1"] = legacyAccount.Phone;
            account["websiteurl"] = legacyAccount.Website;
            account.Id = organizationService.Create(account);
            legacyAccount.Reference = account.ToEntityReference();
            PrintInfo(legacyAccount.AccountId, account);
        }

        /// <summary>
        /// Creates a bookable resource
        /// </summary>
        /// <param name="legacyContact">Legacy contact</param>
        /// <param name="contact">Contact</param>
        static void CreateBookableResource(LegacyResource legacyContact, Entity contact)
        {
            var bookableResource = new Entity("bookableresource");
            bookableResource["name"] = $"{legacyContact.FirstName} {legacyContact.LastName}";
            bookableResource["contactid"] = contact.ToEntityReference();
            bookableResource["resourcetype"] = new OptionSetValue(2); // contact 
            bookableResource["timezone"] = 85; // London
            bookableResource.Id = organizationService.Create(bookableResource);
            legacyContact.BookableReference = bookableResource.ToEntityReference();
            PrintInfo(legacyContact.ResourceId, bookableResource);
        }

        /// <summary>
        /// Creates a contact
        /// </summary>
        /// <param name="legacyContact">Legacy contact</param>
        /// <returns>Contact</returns>
        static Entity CreateContact(LegacyResource legacyContact)
        {
            var contact = new Entity("contact");
            contact["firstname"] = legacyContact.FirstName;
            contact["lastname"] = legacyContact.LastName;
            contact.Id = organizationService.Create(contact);
            legacyContact.Reference = contact.ToEntityReference();
            PrintInfo(legacyContact.ResourceId, contact);
            return contact;
        }
        #endregion

        #region Print helpers
        /// <summary>
        /// Prints a console header
        /// </summary>
        /// <param name="header">header to print</param>
        static void PrintHeader(string header)
        {
            Console.WriteLine("");
            Console.WriteLine("-------------------------------------");
            Console.WriteLine(header);
            Console.WriteLine("-------------------------------------");
        }

        /// <summary>
        /// Prints entity information to the console
        /// </summary>
        /// <param name="srcId">Legacy source record id</param>
        /// <param name="entity">D365 target entity</param>
        static void PrintInfo(string srcId, Entity entity)
        {
            Console.WriteLine($"{entity.LogicalName} created: {srcId} {entity.Id}");
        }
        #endregion

        #region Sample Data
        /// <summary>
        /// Represents the account information associated with the legacy system
        /// </summary>
        class LegacyAccount
        {
            public string AccountId;
            public string Name;
            public string Phone;
            public string Website;
            public EntityReference Reference;
        }

        /// <summary>
        /// Represents the project information associated with the legacy system
        /// </summary>
        class LegacyProject
        {
            public string ProjectId;
            public string AccountId;
            public string Name;
            public string Description;
            public EntityReference Reference;
        }

        /// <summary>
        /// Represents the resource information associated with the legacy system
        /// </summary>
        class LegacyResource
        {
            public string ResourceId;
            public string FirstName;
            public string LastName;
            public string Type;
            public EntityReference Reference;
            public EntityReference BookableReference;
        }

        /// <summary>
        /// Represents the project and team relations associated with the legacy system
        /// </summary>
        class LegacyProjectTeam
        {
            public string ProjectId;
            public string ResourceId;
            public string Role;
            public EntityReference Reference;
        }

        /// <summary>
        /// Represents the task information associated with the legacy system
        /// </summary>
        public class LegacyTask
        {
            public string TaskId;
            public string ParentTaskId;
            public string ProjectId;
            public string Name;
            public double Duration;
            public EntityReference Reference;
        }

        /// <summary>
        /// Represents the task and resource relations associated with the legacy system
        /// </summary>
        class LegacyAssignment
        {
            public string TaskId;
            public string ResourceId;
            public EntityReference Reference;
        }

        /// <summary>
        /// Represents the interdependency between tasks in the legacy system
        /// </summary>
        class LegacyTaskDependency
        {
            public string Task1Id;
            public string Task2Id;
            public string ProjectId;
            public EntityReference Reference;
        }

        /// <summary>
        /// Legacy data
        /// </summary>
        class LegacyData
        {
            public List<LegacyAccount> Accounts;
            public List<LegacyResource> Resources;
            public List<LegacyProject> Projects;
            public List<LegacyTask> Tasks;
            public List<LegacyProjectTeam> ProjectTeams;
            public List<LegacyAssignment> Assignments;
            public List<LegacyTaskDependency> Dependencies;
        }

        /// <summary>
        /// Initializes the legacy data
        /// </summary>
        /// <returns></returns>
        static void InitializeLegacyData()
        {
            data = new LegacyData()
            {
                Accounts = new List<LegacyAccount> {
                        new LegacyAccount() {
                            AccountId = "ACCT_1",
                            Name = "Northwind",
                            Phone = "+11-1234567890",
                            Website = "https://northwind.com"
                        },
                        new LegacyAccount() {
                            AccountId = "ACCT_2",
                            Name = "Litware",
                            Phone = "+44-1286746536",
                            Website = "https://litware.com"
                        }
                },
                Resources = new List<LegacyResource> {
                        new LegacyResource() { ResourceId="RES_1", FirstName="Hallie", LastName="Jacobs", Type="Employee"},
                        new LegacyResource() { ResourceId="RES_2", FirstName="Judy", LastName="Simon", Type="Employee"},
                        new LegacyResource() { ResourceId="RES_3", FirstName="John", LastName="Whyte", Type="Contractor"}
                },
                Projects = new List<LegacyProject> {
                        new LegacyProject() {
                            ProjectId = "PROJ_1",
                            AccountId = "ACCT_1",
                            Name = "Northwind Transformation",
                            Description = "Digital transformation project"
                        },
                        new LegacyProject() {
                            ProjectId = "PROJ_2",
                            AccountId = "ACCT_1",
                            Name = "Northwind Data",
                            Description = "Data migration"
                        },
                        new LegacyProject() {
                            ProjectId = "PROJ_3",
                            AccountId = "ACCT_2",
                            Name = "Litware Digital",
                            Description = "Website launch"
                        }
                },
                Tasks = new List<LegacyTask> {
                    new LegacyTask() { TaskId="TASK_1", ParentTaskId="", ProjectId="PROJ_1",Name="Project Plan", Duration = 0d},
                    new LegacyTask() {
                        TaskId="TASK_2",
                        ParentTaskId="TASK_1",
                        ProjectId="PROJ_1",
                        Name="Create project plan",
                        Duration = 1d
                    },
                    new LegacyTask() { TaskId="TASK_3", ParentTaskId="", ProjectId="PROJ_1", Name="Build", Duration = 9d},
                    new LegacyTask() { TaskId="TASK_4", ParentTaskId="", ProjectId="PROJ_2", Name="Create project plan", Duration = 1d},
                    new LegacyTask() { TaskId="TASK_5", ParentTaskId="", ProjectId="PROJ_2", Name="Build", Duration = 11d},
                    new LegacyTask() { TaskId="TASK_6", ParentTaskId="", ProjectId="PROJ_3", Name="Create project plan", Duration = 1d},
                    new LegacyTask() { TaskId="TASK_7", ParentTaskId="", ProjectId="PROJ_3", Name="Build", Duration = 9d}
                },
                ProjectTeams = new List<LegacyProjectTeam>
                {
                    new LegacyProjectTeam() { ProjectId="PROJ_1", ResourceId="RES_1", Role="Project Manager"},
                    new LegacyProjectTeam() { ProjectId="PROJ_1",ResourceId="RES_2", Role="Team Member"},
                    new LegacyProjectTeam() { ProjectId="PROJ_2",ResourceId="RES_1", Role="Project Manager"},
                    new LegacyProjectTeam() { ProjectId="PROJ_2",ResourceId="RES_2", Role="Team Member"},
                    new LegacyProjectTeam() { ProjectId="PROJ_3",ResourceId="RES_1", Role="Project Manager"},
                    new LegacyProjectTeam() { ProjectId="PROJ_3",ResourceId="RES_3", Role="Team Member"},
                },
                Assignments = new List<LegacyAssignment>
                {
                    new LegacyAssignment() { TaskId="TASK_2", ResourceId="RES_1"},
                    new LegacyAssignment() { TaskId="TASK_3",ResourceId="RES_2"},
                    new LegacyAssignment() { TaskId="TASK_4",ResourceId="RES_1"},
                    new LegacyAssignment() { TaskId="TASK_5",ResourceId="RES_2"},
                    new LegacyAssignment() { TaskId="TASK_6",ResourceId="RES_1"},
                    new LegacyAssignment() { TaskId="TASK_7",ResourceId="RES_3"},
                },
                Dependencies = new List<LegacyTaskDependency>
                {
                    new LegacyTaskDependency() { Task1Id="TASK_2", Task2Id="TASK_3", ProjectId="PROJ_1"},
                    new LegacyTaskDependency() { Task1Id="TASK_4",Task2Id="TASK_5", ProjectId="PROJ_2"},
                    new LegacyTaskDependency() { Task1Id="TASK_6",Task2Id="TASK_7", ProjectId="PROJ_3"},
                }
            };
        }
        #endregion

        #region OrganizationService

        /// <summary>
        /// Returns the application setting by key name
        /// </summary>
        /// <typeparam name="T">Data type of the passed application setting</typeparam>
        /// <param name="name">Name of the setting</param>
        /// <returns>Setting</returns>
        static T GetApplicationSetting<T>(string name)
        {
            object value = Properties.Settings.Default[name];
            if (value == null)
            {
                throw new InvalidOperationException(
                    $"The configuration setting with the name '{name}' could not be read.");
            }

            return (T)value;
        }


        /// <summary>
        /// Initializes Organization Service
        /// </summary>
        static void InitializeOrganizationService()
        {
            string connectionString = GetApplicationSetting<string>("DataverseConnectionString");

            var service = new CrmServiceClient(connectionString);
            if (!service.IsReady)
            {
                throw new InvalidOperationException(
                    $"CrmServiceClient is not ready. Last exception: {service.LastCrmException}");
            }
            organizationService = service;
        }
        #endregion

        #region Call Actions
        /// <summary>
        /// Calls the action to create an operationSet
        /// </summary>
        /// <param name="projectId">project id for the operations to be included in this operationSet</param>
        /// <param name="description">description of this operationSet</param>
        /// <returns>operationSet id</returns>
        static string CallCreateOperationSetAction(Guid projectId, string description)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_CreateOperationSetV1");
            operationSetRequest["ProjectId"] = projectId.ToString();
            operationSetRequest["Description"] = description;
            OrganizationResponse response = organizationService.Execute(operationSetRequest);
            return response["OperationSetId"].ToString();
        }

        /// <summary>
        /// Calls the action to create an entity, only Task and Resource Assignment for now
        /// </summary>
        /// <param name="entity">Task or Resource Assignment</param>
        /// <param name="operationSetId">operationSet id</param>
        /// <returns>OperationSetResponse</returns>

        static OperationSetResponse CallPssCreateAction(Entity entity, string operationSetId)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_PssCreateV1");
            operationSetRequest["Entity"] = entity;
            operationSetRequest["OperationSetId"] = operationSetId;
            return GetOperationSetResponseFromOrgResponse(organizationService.Execute(operationSetRequest));
        }

        /// <summary>
        /// Calls the action to update an entity, only Task for now
        /// </summary>
        /// <param name="entity">Task or Resource Assignment</param>
        /// <param name="operationSetId">operationSet Id</param>
        /// <returns>OperationSetResponse</returns>
        static OperationSetResponse CallPssUpdateAction(Entity entity, string operationSetId)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_PssUpdateV1");
            operationSetRequest["Entity"] = entity;
            operationSetRequest["OperationSetId"] = operationSetId;
            return GetOperationSetResponseFromOrgResponse(organizationService.Execute(operationSetRequest));
        }

        /// <summary>
        /// Calls the action to update an entity, only Task and Resource Assignment for now
        /// </summary>
        /// <param name="recordId">Id of the record to be deleted</param>
        /// <param name="entityLogicalName">Entity logical name of the record</param>
        /// <param name="operationSetId">OperationSet Id</param>
        /// <returns>OperationSetResponse</returns>
        static OperationSetResponse CallPssDeleteAction(string recordId, string entityLogicalName, string operationSetId)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_PssDeleteV1");
            operationSetRequest["RecordId"] = recordId;
            operationSetRequest["EntityLogicalName"] = entityLogicalName;
            operationSetRequest["OperationSetId"] = operationSetId;
            return GetOperationSetResponseFromOrgResponse(organizationService.Execute(operationSetRequest));
        }

        /// <summary>
        /// Calls the action to execute requests in an operationSet
        /// </summary>
        /// <param name="operationSetId">operationSet id</param>
        /// <returns>OperationSetResponse</returns>
        static OperationSetResponse CallExecuteOperationSetAction(string operationSetId)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_ExecuteOperationSetV1");
            operationSetRequest["OperationSetId"] = operationSetId;
            return GetOperationSetResponseFromOrgResponse(organizationService.Execute(operationSetRequest));
        }

        /// <summary>
        /// This can be used to abandon an operationSet that is no longer needed
        /// </summary>
        /// <param name="operationSetId">operationSet id</param>
        /// <returns>OperationSetResponse</returns>
        static OperationSetResponse CallAbandonOperationSetAction(Guid operationSetId)
        {
            OrganizationRequest operationSetRequest = new OrganizationRequest("msdyn_AbandonOperationSetV1");
            operationSetRequest["OperationSetId"] = operationSetId.ToString();
            return GetOperationSetResponseFromOrgResponse(organizationService.Execute(operationSetRequest));
        }


        /// <summary>
        /// Calls the action to create a new project
        /// </summary>
        /// <param name="project">Project</param>
        /// <returns>project Id</returns>
        static Guid CallCreateProjectAction(Entity project)
        {
            OrganizationRequest createProjectRequest = new OrganizationRequest("msdyn_CreateProjectV1");
            createProjectRequest["Project"] = project;
            OrganizationResponse response = organizationService.Execute(createProjectRequest);
            var projectId = Guid.Parse((string)response["ProjectId"]);
            return projectId;
        }

        /// <summary>
        /// Calls the action to create a new project team member
        /// </summary>
        /// <param name="teamMember">Project team member</param>
        /// <returns>project team member Id</returns>
        static Guid CallCreateTeamMemberAction(Entity teamMember)
        {
            OrganizationRequest request = new OrganizationRequest("msdyn_CreateTeamMemberV1");
            request["TeamMember"] = teamMember;
            OrganizationResponse response = organizationService.Execute(request);
            return Guid.Parse((string)response["TeamMemberId"]);
        }

        static OperationSetResponse GetOperationSetResponseFromOrgResponse(OrganizationResponse orgResponse)
        {
            return JsonConvert.DeserializeObject<OperationSetResponse>((string)orgResponse.Results["OperationSetResponse"]);
        }

        /// <summary>
        /// Returns the default bucket assoucated with a project reference
        /// </summary>
        /// <param name="projectReference">Project reference</param>
        /// <returns>Bucket</returns>
        static EntityCollection GetDefaultBucket(EntityReference projectReference)
        {
            var columnsToFetch = new ColumnSet("msdyn_project", "msdyn_name");
            var getDefaultBucket = new QueryExpression("msdyn_projectbucket")
            {
                ColumnSet = columnsToFetch,
                Criteria =
        {
            Conditions =
            {
                new ConditionExpression("msdyn_project", ConditionOperator.Equal, projectReference.Id),
                new ConditionExpression("msdyn_name", ConditionOperator.Equal, "Bucket 1")
}
        }
            };

            return organizationService.RetrieveMultiple(getDefaultBucket);
        }

        /// <summary>
        /// Returns the buket associated with a project
        /// </summary>
        /// <param name="projectReference">Project reference</param>
        /// <returns>Bucket</returns>
        static Entity GetBucket(EntityReference projectReference)
        {
            var bucketCollection = GetDefaultBucket(projectReference);
            if (bucketCollection.Entities.Count > 0)
            {
                return bucketCollection[0].ToEntity<Entity>();
            }

            throw new Exception($"Please open project with id {projectReference.Id} in the Dynamics UI and navigate to the Tasks tab");
        }
        #endregion

        #region OperationSetResponse DataContract

        /// <summary>
        /// Represents the response returned by the OperationSet API
        /// </summary>
        [DataContract]
        class OperationSetResponse
        {
            [DataMember(Name = "operationSetId")]
            public Guid OperationSetId { get; set; }

            [DataMember(Name = "operationSetDetailId")]
            public Guid OperationSetDetailId { get; set; }

            [DataMember(Name = "operationType")]
            public string OperationType { get; set; }

            [DataMember(Name = "recordId")]
            public string RecordId { get; set; }

            [DataMember(Name = "correlationId")]
            public string CorrelationId { get; set; }
        }
        #endregion
    }
}

