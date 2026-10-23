module top (
    input clk,
    input go,
    input abort,
    output logic last,
    output logic busy
);
  typedef enum logic [15:0] {S0 = 16'd1, S1 = 16'd2, S2 = 16'd4, S3 = 16'd8, S4 = 16'd16, S5 = 16'd32, S6 = 16'd64, S7 = 16'd128, S8 = 16'd256, S9 = 16'd512, S10 = 16'd1024, S11 = 16'd2048, S12 = 16'd4096, S13 = 16'd8192, S14 = 16'd16384, S15 = 16'd32768} state_t;
  state_t st, ns;
  always_comb begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S4;
      S4: if (abort) ns = S0; else if (go) ns = S5;
      S5: if (abort) ns = S0; else if (go) ns = S6;
      S6: if (abort) ns = S0; else if (go) ns = S7;
      S7: if (abort) ns = S0; else if (go) ns = S8;
      S8: if (abort) ns = S0; else if (go) ns = S9;
      S9: if (abort) ns = S0; else if (go) ns = S10;
      S10: if (abort) ns = S0; else if (go) ns = S11;
      S11: if (abort) ns = S0; else if (go) ns = S12;
      S12: if (abort) ns = S0; else if (go) ns = S13;
      S13: if (abort) ns = S0; else if (go) ns = S14;
      S14: if (abort) ns = S0; else if (go) ns = S15;
      S15: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always_ff @(posedge clk) begin
    st <= ns;
    last <= (ns == S15);
    busy <= (ns != S0);
  end
endmodule
