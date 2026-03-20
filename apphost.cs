#:sdk Aspire.AppHost.Sdk@13.1.3
#:package Aspire.Hosting.JavaScript@13.1.3
#:package Aspire.Hosting.Python@13.1.3
#:package Aspire.Hosting.GitHub.Models@13.1.3
#:package CommunityToolkit.Aspire.Hosting.SQLite@13.*
#:package Microsoft.Extensions.Configuration.Json@10.*

using Microsoft.Extensions.Configuration;


const string RESOURCE_MCP_MARKITDOWN = "mcp-markitdown";
const string RESOURCE_DB_SQLITE = "sqlite";
const string RESOURCE_DB_NAME = "interviewcoach.db";
const string RESOURCE_PROJECT_AGENT = "agent";

var builder = DistributedApplication.CreateBuilder(args);

var config = builder.Configuration
    .AddJsonFile("apphost.settings.json", optional: true, reloadOnChange: true)
    .AddUserSecrets(typeof(Program).Assembly, optional: true, reloadOnChange: true)
    .Build();

var mcpMarkItDown = builder.AddContainer(RESOURCE_MCP_MARKITDOWN, "mcp/markitdown", "latest")
                           .WithExternalHttpEndpoints()
                           .WithImageTag("latest")
                           .WithHttpEndpoint(3001, 3001)
                           .WithArgs("--http", "--host", "0.0.0.0", "--port", "3001");

var sqlite = builder.AddSqlite(RESOURCE_DB_SQLITE, databaseFileName: RESOURCE_DB_NAME)
    .WithSqliteWeb();

var mcpInterviewData = builder.AddUvicornApp(
        name: "interview-data",
        appDirectory: "./src/interview-data-mcp",
        app: "main:app")
    .WithUv()
    .WithExternalHttpEndpoints()
    .WithHttpEndpoint(port: 8001, env: "PORT", name: "mcp")
    .WithHttpHealthCheck("/health")
    .WaitFor(sqlite);

var agent = builder.AddUvicornApp(
        name: RESOURCE_PROJECT_AGENT,
        appDirectory: "./src/interview-prep-agents",
        app: "main:app")
    .WithUv()
    .WithExternalHttpEndpoints()
    .WithHttpEndpoint(port: 8000, env: "PORT", name: "interview-prep-agents")
    .WithEnvironment("LLM_PROVIDER", builder.Configuration["LLM:Provider"] ?? "github")
    .WithEnvironment("GITHUB_MODELS_TOKEN", builder.Configuration["Github:Token"] ?? "")
    .WithEnvironment("GITHUB_MODELS_MODEL", builder.Configuration["Github:Model"] ?? "openai/gpt-4.1")
    .WithEnvironment("OPENAI_API_KEY", builder.Configuration["OpenAI:ApiKey"] ?? "")
    .WithEnvironment("OPENAI_MODEL", builder.Configuration["OpenAI:Model"] ?? "gpt-4o-mini")
    .WithEnvironment("OPENAI_BASE_URL", builder.Configuration["OpenAI:BaseUrl"] ?? "https://api.openai.com/v1")
    .WithReference(mcpMarkItDown.GetEndpoint("http"))
    .WithReference(mcpInterviewData.GetEndpoint("http"))
    .WithHttpHealthCheck("/health")
    .WaitFor(mcpMarkItDown)
    .WaitFor(mcpInterviewData);

var backend = builder.AddUvicornApp("backend", "./src/backend", "main:app")
    .WithUv()
    .WithExternalHttpEndpoints()
    .WithReference(agent)
    .WithHttpHealthCheck("/health");

var frontend = builder.AddViteApp("frontend", "./src/frontend")
    .WithReference(backend)
    .WaitFor(backend);

backend.PublishWithContainerFiles(frontend, "./static");

builder.Build().Run();
