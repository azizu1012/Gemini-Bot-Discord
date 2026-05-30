const path = require("path");
const projectRoot = __dirname;

module.exports = {
  apps: [
    {
      name: "azuris-bot",
      cwd: projectRoot,
      script: path.join(projectRoot, "run_bot.sh"), // Chạy qua file script để kích hoạt hạ tầng
      args: [], // Biến môi trường và logic được quản lý bên trong script
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
