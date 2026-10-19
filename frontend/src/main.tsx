import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./app/App";
import "./styles.css";

async function boot() {
  if (__MOCK__) {
    const { installMockFetch } = await import("./mock/install");
    installMockFetch();
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter basename="/esl">
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
}
void boot();
