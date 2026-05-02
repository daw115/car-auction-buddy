export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      app_config: {
        Row: {
          ai_analysis_mode: string
          collect_all_prefiltered_results: boolean
          filter_seller_insurance_only: boolean
          id: number
          max_auction_window_hours: number
          min_auction_window_hours: number
          open_all_prefiltered_details: boolean
          updated_at: string
          use_mock_data: boolean
        }
        Insert: {
          ai_analysis_mode?: string
          collect_all_prefiltered_results?: boolean
          filter_seller_insurance_only?: boolean
          id?: number
          max_auction_window_hours?: number
          min_auction_window_hours?: number
          open_all_prefiltered_details?: boolean
          updated_at?: string
          use_mock_data?: boolean
        }
        Update: {
          ai_analysis_mode?: string
          collect_all_prefiltered_results?: boolean
          filter_seller_insurance_only?: boolean
          id?: number
          max_auction_window_hours?: number
          min_auction_window_hours?: number
          open_all_prefiltered_details?: boolean
          updated_at?: string
          use_mock_data?: boolean
        }
        Relationships: []
      }
      clients: {
        Row: {
          contact: string | null
          created_at: string
          id: string
          name: string
          notes: string | null
        }
        Insert: {
          contact?: string | null
          created_at?: string
          id?: string
          name: string
          notes?: string | null
        }
        Update: {
          contact?: string | null
          created_at?: string
          id?: string
          name?: string
          notes?: string | null
        }
        Relationships: []
      }
      operation_logs: {
        Row: {
          client_id: string | null
          created_at: string
          details: Json | null
          duration_ms: number | null
          id: string
          level: string
          message: string
          operation: string
          record_id: string | null
          step: string | null
        }
        Insert: {
          client_id?: string | null
          created_at?: string
          details?: Json | null
          duration_ms?: number | null
          id?: string
          level?: string
          message: string
          operation: string
          record_id?: string | null
          step?: string | null
        }
        Update: {
          client_id?: string | null
          created_at?: string
          details?: Json | null
          duration_ms?: number | null
          id?: string
          level?: string
          message?: string
          operation?: string
          record_id?: string | null
          step?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "operation_logs_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "operation_logs_record_id_fkey"
            columns: ["record_id"]
            isOneToOne: false
            referencedRelation: "records"
            referencedColumns: ["id"]
          },
        ]
      }
      records: {
        Row: {
          ai_input: Json | null
          ai_prompt: string | null
          analysis: Json | null
          analysis_completed_at: string | null
          analysis_started_at: string | null
          analysis_status: string | null
          artifacts_meta: Json | null
          client_id: string | null
          created_at: string
          criteria: Json
          id: string
          listings: Json
          mail_html: string | null
          report_html: string | null
          status: string
          title: string | null
          updated_at: string
        }
        Insert: {
          ai_input?: Json | null
          ai_prompt?: string | null
          analysis?: Json | null
          analysis_completed_at?: string | null
          analysis_started_at?: string | null
          analysis_status?: string | null
          artifacts_meta?: Json | null
          client_id?: string | null
          created_at?: string
          criteria?: Json
          id?: string
          listings?: Json
          mail_html?: string | null
          report_html?: string | null
          status?: string
          title?: string | null
          updated_at?: string
        }
        Update: {
          ai_input?: Json | null
          ai_prompt?: string | null
          analysis?: Json | null
          analysis_completed_at?: string | null
          analysis_started_at?: string | null
          analysis_status?: string | null
          artifacts_meta?: Json | null
          client_id?: string | null
          created_at?: string
          criteria?: Json
          id?: string
          listings?: Json
          mail_html?: string | null
          report_html?: string | null
          status?: string
          title?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "records_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
        ]
      }
      scrape_cache: {
        Row: {
          cache_key: string
          config_snapshot: Json
          created_at: string
          criteria: Json
          expires_at: string
          id: string
          listings: Json
          listings_count: number
          source: string | null
        }
        Insert: {
          cache_key: string
          config_snapshot?: Json
          created_at?: string
          criteria: Json
          expires_at?: string
          id?: string
          listings?: Json
          listings_count?: number
          source?: string | null
        }
        Update: {
          cache_key?: string
          config_snapshot?: Json
          created_at?: string
          criteria?: Json
          expires_at?: string
          id?: string
          listings?: Json
          listings_count?: number
          source?: string | null
        }
        Relationships: []
      }
      watchlist: {
        Row: {
          active: boolean
          buy_now_usd: number | null
          category: string | null
          client_id: string | null
          created_at: string
          current_bid_usd: number | null
          id: string
          lot_id: string | null
          make: string | null
          model: string | null
          notes: string | null
          score: number | null
          snapshot: Json
          source: string | null
          title: string | null
          updated_at: string
          url: string | null
          vin: string | null
          year: number | null
        }
        Insert: {
          active?: boolean
          buy_now_usd?: number | null
          category?: string | null
          client_id?: string | null
          created_at?: string
          current_bid_usd?: number | null
          id?: string
          lot_id?: string | null
          make?: string | null
          model?: string | null
          notes?: string | null
          score?: number | null
          snapshot?: Json
          source?: string | null
          title?: string | null
          updated_at?: string
          url?: string | null
          vin?: string | null
          year?: number | null
        }
        Update: {
          active?: boolean
          buy_now_usd?: number | null
          category?: string | null
          client_id?: string | null
          created_at?: string
          current_bid_usd?: number | null
          id?: string
          lot_id?: string | null
          make?: string | null
          model?: string | null
          notes?: string | null
          score?: number | null
          snapshot?: Json
          source?: string | null
          title?: string | null
          updated_at?: string
          url?: string | null
          vin?: string | null
          year?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "watchlist_client_id_fkey"
            columns: ["client_id"]
            isOneToOne: false
            referencedRelation: "clients"
            referencedColumns: ["id"]
          },
        ]
      }
      watchlist_history: {
        Row: {
          current_bid_usd: number | null
          id: string
          payload: Json | null
          recorded_at: string
          score: number | null
          status: string | null
          watchlist_id: string
        }
        Insert: {
          current_bid_usd?: number | null
          id?: string
          payload?: Json | null
          recorded_at?: string
          score?: number | null
          status?: string | null
          watchlist_id: string
        }
        Update: {
          current_bid_usd?: number | null
          id?: string
          payload?: Json | null
          recorded_at?: string
          score?: number | null
          status?: string | null
          watchlist_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "watchlist_history_watchlist_id_fkey"
            columns: ["watchlist_id"]
            isOneToOne: false
            referencedRelation: "watchlist"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
