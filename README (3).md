# Docker-free local Neo4j runtime

Docker Desktop installation failed on this machine, and the official Neo4j binary CDN
(`dist.neo4j.org`) returns a country-level CloudFront 403. To keep the project on real
Neo4j/Cypher without Docker, this directory contains a **workspace-local Neo4j 5.26.32
runtime** built from official Maven Central artifacts.

## What is actually running

- Neo4j Community embedded engine + Bolt connector
- Data directory: `EnterpriseKG/.runtime/neo4j-home`
- Bolt: `bolt://127.0.0.1:7687`
- Auth: disabled for this local-only embedded runtime; still bound to `127.0.0.1`
- No HTTP Browser in embedded mode (use Streamlit or `src.graph_query`)
- No Windows service, registry entry, PATH change, or global JDK install

The Python project, graph model, Cypher, and Neo4j driver are unchanged.

## Start / stop

From the workspace root:

```powershell
.\start_neo4j.bat        # Docker-free local runtime is preferred automatically
.\start_neo4j_local.bat  # explicit local runtime
.\stop_neo4j.bat
.\stop_neo4j_local.bat
```

First startup takes about 30–60 seconds. Keep the console window open while using the
database. Closing it (or Ctrl+C) stops the embedded server; committed data remains in
`.runtime/neo4j-home`.

If another process already listens on `7687`, the script reports "already listening"
and does not start a second instance.

## Build (only needed if `.runtime` is removed)

The delivery keeps the runnable runtime (JRE + Neo4j JARs + data) but removes the
build-only JDK, Maven, Maven cache, and downloaded archives to keep the workspace
small. To rebuild, download:

- Temurin JDK 21:
  `https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse`
- Apache Maven 3.9.9:
  `https://repo1.maven.org/maven2/org/apache/maven/apache-maven/3.9.9/apache-maven-3.9.9-bin.zip`

Extract both under `EnterpriseKG/.runtime/jdk` and `.runtime/maven`, then run:

```powershell
$root = (Get-Location).Path
$rt = "$root\EnterpriseKG\.runtime"
$jdk = Get-ChildItem "$rt\jdk" -Directory | Select-Object -First 1
$mvn = Get-ChildItem "$rt\maven" -Recurse -Filter mvn.cmd | Select-Object -First 1

$env:JAVA_HOME = $jdk.FullName
$env:PATH = "$($jdk.FullName)\bin;$env:PATH"

New-Item -ItemType Directory -Force -Path "$rt\m2" | Out-Null
cd EnterpriseKG\local_neo4j
& $mvn.FullName -s "$rt\settings.xml" -DskipTests package
```

`settings.xml` under `.runtime` pins the local repository to the workspace.

This writes:

- `target/classes/com/enterprisekg/localneo4j/EmbeddedNeo4jServer.class`
- all runtime JARs to `.runtime/lib`
- a portable JRE is expected at `.runtime/jre/<temurin-jre>/bin/java.exe`

## Reset the graph

Stop Neo4j, delete the data directory, then rebuild from CSV:

```powershell
.\stop_neo4j.bat
Remove-Item -Recurse -Force EnterpriseKG\.runtime\neo4j-home
.\start_neo4j.bat
.\run_pipeline.bat
```

`graph_builder --reset` only deletes nodes with `project = "EnterpriseKG"`; it does not
wipe the whole database.

## Security note

This runner disables authentication because it is a local, single-user embedded
instance bound to loopback. It must not be exposed on a network interface. For a
shared/production deployment use the Docker Compose file (Neo4j server, auth enabled)
or a managed Neo4j instance.
