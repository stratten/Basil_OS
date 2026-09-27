export interface UseCase {
  id: string;
  label: string;
  icon: React.ReactNode;
  requestText: string;
  outputText: string;
  duration: number;
  contextComponent: React.ReactNode;
}
