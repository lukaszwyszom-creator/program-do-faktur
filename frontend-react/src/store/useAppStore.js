import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useAppStore = create(
  persist(
    (set) => ({
      mode: 'simple', // 'simple' | 'advanced'

      // NIP sprzedawcy zapamiętany do operacji KSeF
      sellerNip: '',

      // Filtry wspólne
      filters: {
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
          filters: { status: '', issue_date_from: '', issue_date_to: '', contractor: '' },
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
