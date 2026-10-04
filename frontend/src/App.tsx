import { useEffect } from "react";

import AnalysisPanel from "./components/AnalysisPanel/AnalysisPanel";
import CollectionView from "./components/Collection/CollectionView";
import LinkDialog from "./components/Collection/LinkDialog";
import PromptDetail from "./components/Collection/PromptDetail";
import PromptEditor from "./components/Collection/PromptEditor";
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
  const view = useUi((s) => s.view);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="flex h-full min-w-[1280px] flex-col">
      <TopBar />
      {view === "collection" ? (
        <CollectionView />
      ) : (
        <div className="flex min-h-0 flex-1">
          {sidebarOpen && <FilterSidebar />}
          <main className="flex min-w-0 flex-1 flex-col">
            <Timeline />
            <Grid />
          </main>
          <AnalysisPanel />
        </div>
      )}
      <PromptDetail />
      <DetailView />
      <CompareView />
      <FileActions />
      <PromptEditor />
      <LinkDialog />
    </div>
  );
}
