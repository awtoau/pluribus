module top (
    input clk,
    input go,
    input abort,
    output logic last,
    output logic busy
);
  typedef enum logic [1:0] {S0 = 2'd0, S1 = 2'd1, S2 = 2'd2, S3 = 2'd3} state_t;
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
