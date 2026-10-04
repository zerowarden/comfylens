import { useEffect } from "react";

import AnalysisPanel from "./components/AnalysisPanel/AnalysisPanel";
import CompareView from "./components/CompareView/CompareView";
import DetailView from "./components/DetailView/DetailView";
import FileActions from "./components/FileActions";
import FilterSidebar from "./components/FilterSidebar";
import Grid from "./components/Grid";
import Timeline from "./components/Timeline";
import TopBar from "./components/TopBar";
import { useUi } from "./state/ui";

export default function App() {
  const theme = useUi((s) => s.theme);
  const sidebarOpen = useUi((s) => s.sidebarOpen);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="flex h-full min-w-[1280px] flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {sidebarOpen && <FilterSidebar />}
        <main className="flex min-w-0 flex-1 flex-col">
          <Timeline />
          <Grid />
        </main>
        <AnalysisPanel />
      </div>
      <DetailView />
      <CompareView />
      <FileActions />
    </div>
  );
}
