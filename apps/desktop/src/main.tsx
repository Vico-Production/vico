import React from "react";
import ReactDOM from "react-dom/client";
import { setTransport } from "./lib/api";
import { currentView, inTauri } from "./lib/bus";
import { demoTransport } from "./lib/demo";
import "./styles/vico.css";
import { AuraWindow, PromptWindow, Stage } from "./views/Windows";

if (!inTauri && new URLSearchParams(window.location.search).has("demo")) setTransport(demoTransport());

void currentView().then((view) => {
  document.documentElement.dataset.view = view;
  const root = ReactDOM.createRoot(document.getElementById("root") as HTMLElement);
  root.render(
    <React.StrictMode>
      {view === "aura" ? <AuraWindow /> : view === "prompt" ? <PromptWindow /> : <Stage />}
    </React.StrictMode>,
  );
});
