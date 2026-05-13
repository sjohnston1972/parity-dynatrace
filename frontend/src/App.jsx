import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import { DialogProvider } from './components/Dialog';
import { SnapshotProvider } from './hooks/useSnapshotStatus';
import Dashboard from './pages/Dashboard';
import Topology from './pages/Topology';
import Devices from './pages/Devices';
import Insights from './pages/Insights';
import Approvals from './pages/Approvals';
import Snapshots from './pages/Snapshots';
import Executions from './pages/Executions';
import Pipeline from './pages/Pipeline';
import Settings from './pages/Settings';

export default function App() {
  return (
    <DialogProvider>
    <SnapshotProvider>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="topology" element={<Topology />} />
        <Route path="devices" element={<Devices />} />
        <Route path="snapshots" element={<Snapshots />} />
        <Route path="insights" element={<Insights />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="executions" element={<Executions />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
    </SnapshotProvider>
    </DialogProvider>
  );
}
