import { create } from 'zustand';
import { persist } from 'zustand/middleware';

function currentMonthValue() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

export const useAppStore = create(
  persist(
    (set) => ({
      mode: 'simple', // 'simple' | 'advanced'

      // NIP sprzedawcy zapamiętany do operacji KSeF
      sellerNip: '',

      // Filtry wspólne
      filters: {
        month: currentMonthValue(),
        status: '',
        issue_date_from: '',
        issue_date_to: '',
        contractor: '',
      },

      // Stan formularza faktury (Simple mode)
      draftInvoice: null,

      setMode: (mode) => set({ mode }),

      setSellerNip: (nip) => set({ sellerNip: nip }),

      setFilters: (patch) =>
        set((s) => ({ filters: { ...s.filters, ...patch } })),

      resetFilters: () =>
        set({
          filters: { month: currentMonthValue(), status: '', issue_date_from: '', issue_date_to: '', contractor: '' },
        }),

      setDraftInvoice: (invoice) => set({ draftInvoice: invoice }),

      clearDraft: () => set({ draftInvoice: null }),
    }),
    {
      name: 'faktura-app',
      partialize: (s) => ({ mode: s.mode, sellerNip: s.sellerNip }),
    }
  )
);
