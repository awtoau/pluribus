module top (
    input clk,
    input go,
    input abort,
    output logic last,
    output logic busy
);
  typedef enum logic [3:0] {S0 = 4'd1, S1 = 4'd2, S2 = 4'd4, S3 = 4'd8} state_t;
  state_t st, ns;
  always_comb begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always_ff @(posedge clk) begin
    st <= ns;
    last <= (ns == S3);
    busy <= (ns != S0);
  end
endmodule
