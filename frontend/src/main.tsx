import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { applyTheme, readTheme } from "./lib/auth";
import "./styles.css";

applyTheme(readTheme());

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
