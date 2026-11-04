package com.enterprisekg.localneo4j;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;

import org.neo4j.configuration.GraphDatabaseSettings;
import org.neo4j.configuration.connectors.BoltConnector;
import org.neo4j.configuration.helpers.SocketAddress;
import org.neo4j.dbms.api.DatabaseManagementService;
import org.neo4j.dbms.api.DatabaseManagementServiceBuilder;
import org.neo4j.graphdb.GraphDatabaseService;

/**
 * Docker-free local Neo4j runtime with a fixed, persistent data directory.
 *
 * <p>Uses the official embedded Neo4j engine and exposes a local Bolt endpoint.
 * No system service, no registry entry, no global Java installation, and no
 * Docker are required. The HTTP Browser is not part of this embedded mode;
 * use the Streamlit app or {@code src.graph_query} for the UI.</p>
 */
public final class EmbeddedNeo4jServer {

    private EmbeddedNeo4jServer() {
    }

    public static void main(String[] args) throws Exception {
        String homeValue = System.getProperty("enterprisekg.data", "data");
        String pidFileValue = System.getProperty("enterprisekg.pid", "");
        int boltPort = Integer.parseInt(System.getProperty("enterprisekg.bolt", "7687"));
        Path home = Path.of(homeValue).toAbsolutePath().normalize();
        Files.createDirectories(home);

        DatabaseManagementService managementService = new DatabaseManagementServiceBuilder(home)
                .setConfig(BoltConnector.enabled, true)
                .setConfig(BoltConnector.listen_address, new SocketAddress("127.0.0.1", boltPort))
                .setConfig(BoltConnector.advertised_address, new SocketAddress("127.0.0.1", boltPort))
                .setConfig(GraphDatabaseSettings.auth_enabled, false)
                .build();

        GraphDatabaseService database = managementService.database(GraphDatabaseSettings.DEFAULT_DATABASE_NAME);

        if (!pidFileValue.isBlank()) {
            Path pidFile = Path.of(pidFileValue).toAbsolutePath().normalize();
            Files.createDirectories(pidFile.getParent());
            Files.writeString(pidFile, Long.toString(ProcessHandle.current().pid()));
        }

        System.out.println("LOCAL_NEO4J_READY");
        System.out.println("LOCAL_NEO4J_BOLT=bolt://127.0.0.1:" + boltPort);
        System.out.println("LOCAL_NEO4J_DATA=" + home);
        System.out.println("LOCAL_NEO4J_DATABASE=" + database.databaseName());
        System.out.flush();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                managementService.shutdown();
            } catch (Exception ignored) {
                // Best-effort shutdown on Ctrl+C.
            }
        }));

        new CountDownLatch(1).await();
    }
}
