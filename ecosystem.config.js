const path = require("path");

const projectRoot = __dirname;
const enableServer = String(process.env.BOT_ENABLE_SERVER || "").trim() === "1";

module.exports = {
  apps: [
    {
      name: "azuris-bot",
      cwd: projectRoot,
      script: path.join(projectRoot, "run_bot.py"),
      args: enableServer ? ["--server"] : [],
      interpreter: path.join(projectRoot, "venv", "bin", "python3"),
      watch: false,
      max_memory_restart: "1G",
      autorestart: true,
      merge_logs: true,
      out_file: path.join(projectRoot, "logs", "azuris-bot-out.log"),
      error_file: path.join(projectRoot, "logs", "azuris-bot-error.log"),
      time: true,
      env: {
        NODE_ENV: "production",
        BOT_ENABLE_SERVER: enableServer ? "1" : "0",
      },
    },
  ],
};
