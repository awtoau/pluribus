module top (
    input clk,
    input go,
    input abort,
    output logic last,
    output logic busy
);
  typedef enum logic [2:0] {S0 = 3'd0, S1 = 3'd1, S2 = 3'd2, S3 = 3'd3, S4 = 3'd4, S5 = 3'd5, S6 = 3'd6, S7 = 3'd7} state_t;
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
      S7: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always_ff @(posedge clk) begin
    st <= ns;
    last <= (ns == S7);
    busy <= (ns != S0);
  end
endmodule
