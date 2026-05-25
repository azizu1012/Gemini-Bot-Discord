const path = require("path");

const projectRoot = __dirname;
const defaultInterpreter = process.platform === "win32" ? "python" : "python3";
const interpreter = String(process.env.AZURIS_PYTHON || process.env.PYTHON || defaultInterpreter).trim();

module.exports = {
  apps: [
    {
      name: "azuris-bot",
      cwd: projectRoot,
      script: path.join(projectRoot, "run_bot.py"),
      args: [], // ÉP CỨNG CHẾ ĐỘ PRODUCTION: UP CẢ BOT CORE VÀ API GATEWAY SERVER
      interpreter,
      watch: false,
      max_memory_restart: "3G",
      autorestart: true,
      merge_logs: true,
      out_file: path.join(projectRoot, "logs", "azuris-bot-out.log"),
      error_file: path.join(projectRoot, "logs", "azuris-bot-error.log"),
      time: true,
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};
